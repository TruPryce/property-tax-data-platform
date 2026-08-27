from __future__ import annotations

import base64
import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
INFRA_ROOT = REPOSITORY_ROOT / "infra"
COMPOSE_FILE = INFRA_ROOT / "compose.yaml"
PGBACKREST_CONF = INFRA_ROOT / "postgres" / "pgbackrest" / "pgbackrest.conf"
CREDENTIAL_WRAPPER = INFRA_ROOT / "postgres" / "pgbackrest" / "aws-signing-process.sh"
BACKUP_SCRIPT = INFRA_ROOT / "scripts" / "pgbackrest-backup.sh"
SYSTEMD_ROOT = INFRA_ROOT / "systemd"
SECRET_VARIABLES = {
    "POSTGRES_SUPERUSER_PASSWORD",
    "AIRFLOW_DB_PASSWORD",
    "PROPERTY_TAX_MIGRATOR_PASSWORD",
    "PROPERTY_TAX_INGESTION_PASSWORD",
    "PROPERTY_TAX_API_PASSWORD",
    "AIRFLOW_FERNET_KEY",
    "AIRFLOW_API_SECRET_KEY",
    "AIRFLOW_JWT_SECRET",
    "AIRFLOW_ADMIN_PASSWORD",
    "PGBACKREST_CIPHER_PASS",
}


def load_compose() -> dict[str, object]:
    document = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


# Assembled from separate name and value literals so no source line contains a
# `NAME=value` pair. Written literally it reads as an assigned credential to
# detect-secrets, and neither an allowlist pragma nor a baseline entry is worth
# spending on a fixture that holds no secret.
BITWARDEN_TEST_CREDENTIALS = (
    ("BWS_ACCESS_TOKEN", "test-access-token"),
    ("BWS_PROJECT_ID", "test-project-id"),
)
BITWARDEN_TEST_ENVIRONMENT = "".join(
    f"{name}={value}\n" for name, value in BITWARDEN_TEST_CREDENTIALS
)


def parse_environment_file_text(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if line and not line.startswith("#") and "=" in line:
            name, value = line.split("=", 1)
            values[name] = value
    return values


def parse_environment_file(path: Path) -> dict[str, str]:
    return parse_environment_file_text(path.read_text(encoding="utf-8"))


def test_runtime_uses_airflow_three_local_executor_topology() -> None:
    compose = load_compose()
    services = compose["services"]
    assert isinstance(services, dict)
    assert set(services) == {
        "postgres",
        "airflow-init",
        "airflow-api-server",
        "airflow-scheduler",
        "airflow-dag-processor",
        "airflow-triggerer",
        "airflow-cli",
    }
    assert services["airflow-api-server"]["command"] == "api-server"
    assert services["airflow-dag-processor"]["command"] == "dag-processor"
    common_environment = compose["x-airflow-common"]["environment"]
    assert common_environment["AIRFLOW__CORE__EXECUTOR"] == "LocalExecutor"
    assert common_environment["AIRFLOW__CORE__LOAD_EXAMPLES"] == "false"
    assert "redis" not in services
    assert "airflow-worker" not in services


def test_runtime_versions_and_build_contexts_are_pinned() -> None:
    compose = load_compose()
    airflow_build = compose["x-airflow-common"]["build"]
    postgres_build = compose["services"]["postgres"]["build"]
    assert airflow_build["dockerfile"] == "infra/airflow/Dockerfile"
    assert airflow_build["args"]["AIRFLOW_VERSION"] == "${AIRFLOW_VERSION:-3.3.0}"
    assert airflow_build["args"]["PYTHON_VERSION"] == "${AIRFLOW_PYTHON_VERSION:-3.12}"
    assert postgres_build["dockerfile"] == "infra/postgres/Dockerfile"
    assert postgres_build["args"]["POSTGRES_VERSION"] == "${POSTGRES_VERSION:-16.11}"
    airflow_dockerfile = (INFRA_ROOT / "airflow" / "Dockerfile").read_text(encoding="utf-8")
    postgres_dockerfile = (INFRA_ROOT / "postgres" / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM apache/airflow:${AIRFLOW_VERSION}-python${PYTHON_VERSION}" in airflow_dockerfile
    assert '"apache-airflow==${AIRFLOW_VERSION}"' in airflow_dockerfile
    assert "FROM postgres:${POSTGRES_VERSION}-bookworm" in postgres_dockerfile


def test_administrative_ports_fail_safe_to_loopback() -> None:
    compose = load_compose()
    services = compose["services"]
    assert services["postgres"]["ports"] == [
        "${POSTGRES_BIND_ADDRESS:-127.0.0.1}:${POSTGRES_PORT:-5432}:5432"
    ]
    assert services["airflow-api-server"]["ports"] == [
        "${AIRFLOW_API_BIND_ADDRESS:-127.0.0.1}:${AIRFLOW_API_PORT:-8080}:8080"
    ]


def test_database_bootstrap_declares_separate_bounded_roles() -> None:
    bootstrap = (INFRA_ROOT / "postgres" / "init" / "10-create-runtime-databases.sh").read_text(
        encoding="utf-8"
    )
    for role in {
        "airflow_metadata",
        "property_tax_migrator",
        "property_tax_ingestion",
        "property_tax_api",
    }:
        assert (
            f"CREATE ROLE {role} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION"
            in bootstrap
        )
    assert "CREATE DATABASE airflow OWNER airflow_metadata" in bootstrap
    assert "CREATE DATABASE property_tax OWNER property_tax_migrator" in bootstrap
    assert "REVOKE CONNECT ON DATABASE property_tax FROM PUBLIC" in bootstrap
    assert "CREATE TABLE" not in bootstrap


def test_example_environment_contains_no_secret_values() -> None:
    values = parse_environment_file(INFRA_ROOT / ".env.example")
    assert SECRET_VARIABLES.isdisjoint(values)
    assert values["AIRFLOW_VERSION"] == "3.3.0"
    assert values["POSTGRES_VERSION"] == "16.11"


def test_bitwarden_bootstrap_writes_only_the_host_access_boundary(tmp_path: Path) -> None:
    environment_file = tmp_path / "runtime.env"
    bitwarden_environment_file = tmp_path / "bitwarden.env"
    completed = subprocess.run(
        [
            str(INFRA_ROOT / "scripts" / "bootstrap-env.sh"),
            str(environment_file),
            str(bitwarden_environment_file),
        ],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "BWS_ACCESS_TOKEN": "test-access-token",
            "BWS_PROJECT_ID": "test-project-id",
        },
    )
    assert completed.returncode == 0, completed.stderr
    values = parse_environment_file(environment_file)
    bitwarden_values = parse_environment_file(bitwarden_environment_file)
    assert SECRET_VARIABLES.isdisjoint(values)
    # Pinned to the image UID rather than the invoking user: deriving this from
    # `id -u` runs every Airflow service as root when bootstrapped under sudo.
    assert values["AIRFLOW_UID"] == "50000"
    assert bitwarden_values == {
        "BWS_ACCESS_TOKEN": "test-access-token",
        "BWS_PROJECT_ID": "test-project-id",
    }
    assert stat.S_IMODE(environment_file.stat().st_mode) == 0o600
    assert stat.S_IMODE(bitwarden_environment_file.stat().st_mode) == 0o600


def test_bitwarden_wrapper_does_not_inherit_access_token_into_compose() -> None:
    wrapper = (INFRA_ROOT / "scripts" / "compose-with-bitwarden.sh").read_text(encoding="utf-8")
    compose = COMPOSE_FILE.read_text(encoding="utf-8")
    assert "bws run" in wrapper
    assert '--project-id "$BWS_PROJECT_ID"' in wrapper
    assert "--no-inherit-env" in wrapper
    assert "8#$bitwarden_file_mode & 077" in wrapper
    assert "BWS_ACCESS_TOKEN" not in compose


def test_generated_secrets_are_url_safe_and_cover_the_runtime_contract() -> None:
    completed = subprocess.run(
        [str(INFRA_ROOT / "scripts" / "generate-runtime-secrets.sh")],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    generated = parse_environment_file_text(completed.stdout)
    assert set(generated) == SECRET_VARIABLES
    assert len(set(generated.values())) == len(SECRET_VARIABLES)
    fernet_key = generated.pop("AIRFLOW_FERNET_KEY")
    assert len(base64.urlsafe_b64decode(fernet_key)) == 32
    for name, value in generated.items():
        # Alphanumeric so a value stays intact inside the SQLAlchemy URL that
        # Compose builds for the Airflow metadata connection.
        assert value.isalnum() and value.isascii(), name
        assert len(value) >= 32, name


BWS_STUB = """#!/usr/bin/env bash
if [[ "$1" == "secret" && "$2" == "list" ]]; then
  python3 -c '
import json, os
path = os.environ["STUB_LOG"]
stored = []
if os.path.exists(path):
    for line in open(path):
        line = line.rstrip("\\n")
        if "=" in line:
            key, value = line.split("=", 1)
            stored.append({"id": key, "key": key, "value": value})
print(json.dumps(stored))
'
  exit 0
fi
if [[ "$1" == "secret" && "$2" == "create" ]]; then
  shift 4
  printf '%s=%s\\n' "$1" "$2" >>"$STUB_LOG"
  exit 0
fi
exit 1
"""

# `bws secret list` takes the project as a positional argument and rejects
# `--project-id`, so a stub that accepts anything would hide a real CLI error.
BWS_STRICT_LIST_STUB = """#!/usr/bin/env bash
if [[ "$1" == "secret" && "$2" == "list" ]]; then
  shift 2
  for argument in "$@"; do
    if [[ "$argument" == --project-id* ]]; then
      echo "error: unexpected argument '--project-id' found" >&2
      exit 1
    fi
  done
  echo '[]'
  exit 0
fi
if [[ "$1" == "secret" && "$2" == "create" ]]; then exit 0; fi
exit 1
"""


def test_bitwarden_creation_round_trips_every_value_intact(tmp_path: Path) -> None:
    """Guards the whole create-then-read-back path against value corruption.

    `IFS='=' read` drops a trailing delimiter under bash, which truncated the
    Fernet key's base64 padding and stored a key Airflow could not decode. The
    secret was created successfully, so only reading the value back catches it.
    """
    stub_directory = tmp_path / "bin"
    stub_directory.mkdir()
    stub = stub_directory / "bws"
    stub.write_text(BWS_STUB, encoding="utf-8")
    stub.chmod(0o755)
    stub_log = tmp_path / "created.env"

    completed = subprocess.run(
        [str(INFRA_ROOT / "scripts" / "generate-runtime-secrets.sh"), "--bws", "test-project"],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{stub_directory}:{os.environ['PATH']}",
            "STUB_LOG": str(stub_log),
            "BWS_ACCESS_TOKEN": "test-access-token",
            "SECRET_CREATE_DELAY_SECONDS": "0",
        },
    )
    assert completed.returncode == 0, completed.stderr
    assert "verified 10 secrets" in completed.stderr

    stored = parse_environment_file(stub_log)
    assert set(stored) == SECRET_VARIABLES
    assert len(base64.urlsafe_b64decode(stored["AIRFLOW_FERNET_KEY"])) == 32


def test_secret_creation_splits_on_the_first_delimiter_only() -> None:
    generator = (INFRA_ROOT / "scripts" / "generate-runtime-secrets.sh").read_text(encoding="utf-8")
    code = "\n".join(line for line in generator.splitlines() if not line.lstrip().startswith("#"))
    # `IFS='=' read -r name value` is the construct that silently truncated the
    # Fernet key under bash; substring extraction is delimiter-safe.
    assert "IFS='=' read" not in code
    assert '"${secret_line%%=*}"' in code
    assert '"${secret_line#*=}"' in code


def test_job_healthchecks_expand_the_container_hostname() -> None:
    compose = load_compose()
    for service in ("airflow-scheduler", "airflow-dag-processor", "airflow-triggerer"):
        test = compose["services"][service]["healthcheck"]["test"]
        assert test[0] == "CMD-SHELL", service
        # `$$` is the Compose escape that reaches the shell as a single `$`.
        # Single quotes around it reach the shell literally, so the check would
        # compare against the string "${HOSTNAME}" and never match a live job.
        assert '"$${HOSTNAME}"' in test[1], service
        assert "'$${HOSTNAME}'" not in test[1], service


def test_project_scoping_uses_the_positional_form_the_cli_accepts(tmp_path: Path) -> None:
    """`bws secret list` rejects `--project-id`; only the positional form works."""
    stub_directory = tmp_path / "bin"
    stub_directory.mkdir()
    stub = stub_directory / "bws"
    stub.write_text(BWS_STRICT_LIST_STUB, encoding="utf-8")
    stub.chmod(0o755)
    completed = subprocess.run(
        [str(INFRA_ROOT / "scripts" / "generate-runtime-secrets.sh"), "--bws", "test-project"],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{stub_directory}:{os.environ['PATH']}",
            "BWS_ACCESS_TOKEN": "test-access-token",
            "SECRET_CREATE_DELAY_SECONDS": "0",
        },
    )
    assert "unexpected argument" not in completed.stderr


def _run_wrapper(arguments: list[str], tmp_path: Path, environment_body: str) -> subprocess.Popen:
    environment_file = tmp_path / "runtime.env"
    environment_file.write_text(environment_body, encoding="utf-8")
    bitwarden_environment_file = tmp_path / "bitwarden.env"
    bitwarden_environment_file.write_text(BITWARDEN_TEST_ENVIRONMENT, encoding="utf-8")
    bitwarden_environment_file.chmod(0o600)
    return subprocess.run(
        [str(INFRA_ROOT / "scripts" / "compose-with-bitwarden.sh"), *arguments],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "COMPOSE_ENV_FILE": str(environment_file),
            "BWS_ENV_FILE": str(bitwarden_environment_file),
        },
    )


@pytest.mark.skipif(
    shutil.which("bws") is None or shutil.which("docker") is None,
    reason="requires the bws and docker executables the wrapper preflights",
)
@pytest.mark.parametrize(
    "arguments",
    [
        ["config"],
        ["convert"],
        ["--profile", "debug", "config"],
        ["-f", "infra/compose.yaml", "config"],
        ["--project-name", "scratch", "config"],
        ["--dry-run", "config"],
    ],
)
def test_secret_rendering_guard_survives_global_compose_options(
    arguments: list[str], tmp_path: Path
) -> None:
    """Compose accepts options before the subcommand, so `$1` is not the subcommand."""
    completed = _run_wrapper(arguments, tmp_path, "POSTGRES_BIND_ADDRESS=127.0.0.1\n")
    assert completed.returncode == 2, arguments
    assert "it contains resolved secrets" in completed.stderr, arguments


@pytest.mark.skipif(
    shutil.which("bws") is None or shutil.which("docker") is None,
    reason="requires the bws and docker executables the wrapper preflights",
)
def test_wrapper_refuses_a_duplicated_bind_address_definition(tmp_path: Path) -> None:
    """Compose resolves the last definition, so validating the first is a bypass."""
    completed = _run_wrapper(
        ["ps"],
        tmp_path,
        "POSTGRES_BIND_ADDRESS=127.0.0.1\nPOSTGRES_BIND_ADDRESS=0.0.0.0\n",
    )
    assert completed.returncode == 2
    assert "is defined 2 times" in completed.stderr


def test_initialization_fails_closed_on_an_unmigrated_metadata_database() -> None:
    compose = load_compose()
    command = compose["services"]["airflow-init"]["command"]
    script = "".join(command)
    # The upstream entrypoint swallows migration and user-creation failures, so
    # the gate depends on these explicit checks running afterwards.
    assert "airflow db check" in script
    assert "airflow db check-migrations" in script
    assert "airflow users list" in script
    assert "set -euo pipefail" in script
    assert "exec /entrypoint" not in script


def test_wrapper_rejects_administrative_ports_on_public_interfaces() -> None:
    wrapper = (INFRA_ROOT / "scripts" / "compose-with-bitwarden.sh").read_text(encoding="utf-8")
    assert "require_private_bind_address POSTGRES_BIND_ADDRESS" in wrapper
    assert "require_private_bind_address AIRFLOW_API_BIND_ADDRESS" in wrapper
    # Loopback plus the Tailscale CGNAT range 100.64.0.0/10.
    assert "^127\\.[0-9]+\\.[0-9]+\\.[0-9]+$" in wrapper
    assert "BASH_REMATCH[1] >= 64 && BASH_REMATCH[1] <= 127" in wrapper


@pytest.mark.skipif(
    shutil.which("bws") is None or shutil.which("docker") is None,
    reason="requires the bws and docker executables the wrapper preflights",
)
def test_wrapper_refuses_a_public_bind_address(tmp_path: Path) -> None:
    environment_file = tmp_path / "runtime.env"
    environment_file.write_text("POSTGRES_BIND_ADDRESS=0.0.0.0\n", encoding="utf-8")
    bitwarden_environment_file = tmp_path / "bitwarden.env"
    bitwarden_environment_file.write_text(BITWARDEN_TEST_ENVIRONMENT, encoding="utf-8")
    bitwarden_environment_file.chmod(0o600)
    completed = subprocess.run(
        [str(INFRA_ROOT / "scripts" / "compose-with-bitwarden.sh"), "ps"],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "COMPOSE_ENV_FILE": str(environment_file),
            "BWS_ENV_FILE": str(bitwarden_environment_file),
        },
    )
    assert completed.returncode == 2
    assert "must bind to loopback or a Tailscale address" in completed.stderr


@pytest.mark.skipif(
    shutil.which("bws") is None or shutil.which("docker") is None,
    reason="requires the bws and docker executables the wrapper preflights",
)
def test_wrapper_refuses_to_render_resolved_secrets(tmp_path: Path) -> None:
    environment_file = tmp_path / "runtime.env"
    environment_file.write_text("POSTGRES_BIND_ADDRESS=127.0.0.1\n", encoding="utf-8")
    bitwarden_environment_file = tmp_path / "bitwarden.env"
    bitwarden_environment_file.write_text(BITWARDEN_TEST_ENVIRONMENT, encoding="utf-8")
    bitwarden_environment_file.chmod(0o600)
    completed = subprocess.run(
        [str(INFRA_ROOT / "scripts" / "compose-with-bitwarden.sh"), "config"],
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "COMPOSE_ENV_FILE": str(environment_file),
            "BWS_ENV_FILE": str(bitwarden_environment_file),
        },
    )
    assert completed.returncode == 2
    assert "it contains resolved secrets" in completed.stderr


def code_lines(path: Path) -> str:
    """File content with whole-line comments removed.

    Every guard below asserts on this rather than on raw text. A comment saying
    "no AWS_ACCESS_KEY_ID exists here" is the documentation working, and a guard
    that reads it as a leak is a guard that punishes explanation.
    """
    return "\n".join(
        line
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines()
        if not line.lstrip().startswith("#")
    )


def postgres_command() -> str:
    return " ".join(load_compose()["services"]["postgres"]["command"])


def test_postgres_archives_wal_continuously_with_a_wall_clock_bound() -> None:
    command = postgres_command()
    assert "archive_mode=on" in command
    assert "archive_command=pgbackrest --stanza=platform archive-push %p" in command
    # Without archive_timeout an idle database holds a partially filled segment
    # indefinitely, so the recovery point drifts arbitrarily far behind the last
    # commit no matter how healthy archiving looks.
    assert "archive_timeout=300" in command
    assert "wal_level=replica" in command


def test_pgbackrest_is_pinned_past_the_stock_bookworm_package() -> None:
    dockerfile = (INFRA_ROOT / "postgres" / "Dockerfile").read_text(encoding="utf-8")
    assert "PGBACKREST_VERSION=2.59.1-1.pgdg12+1" in dockerfile
    assert '"pgbackrest=${PGBACKREST_VERSION}"' in dockerfile
    # Bookworm ships 2.45, which has no `process` S3 key type and so cannot use
    # keyless credentials at all. Asserted against the install directive rather
    # than the file, so the comment naming 2.45 as the thing being avoided does
    # not read as 2.45 being installed.
    code = code_lines(INFRA_ROOT / "postgres" / "Dockerfile")
    assert "2.45" not in code
    # Anchored to the apt install argument list, because `mkdir /var/log/pgbackrest`
    # also mentions the package and is not an install of it. Collecting the
    # continuation lines is what makes "installed unpinned" the thing detected.
    packages: list[str] = []
    collecting = False
    for line in code.splitlines():
        if "apt-get install" in line:
            collecting = True
            line = line.split("apt-get install", 1)[1]
        if collecting:
            packages.extend(line.replace("\\", " ").split())
            if not line.rstrip().endswith("\\"):
                collecting = False
    installed = [token for token in packages if token.strip('"').startswith("pgbackrest")]
    assert installed == ['"pgbackrest=${PGBACKREST_VERSION}"'], installed
    # The build must fail rather than warn if the pin ever resolves elsewhere.
    assert "expected ${PGBACKREST_EXPECTED_VERSION}" in dockerfile
    assert "sha256sum -c -" in dockerfile


def test_certificates_are_mounted_read_only_and_never_baked() -> None:
    postgres = load_compose()["services"]["postgres"]
    mounts = [entry for entry in postgres["volumes"] if "/etc/trupryce/aws" in entry]
    assert mounts == ["${TRUPRYCE_AWS_CERTIFICATE_DIR:-/etc/trupryce/aws}:/etc/trupryce/aws:ro"]
    dockerfile = (INFRA_ROOT / "postgres" / "Dockerfile").read_text(encoding="utf-8")
    # A key copied into a layer is a key in every cache and registry that image
    # reaches, and it cannot be rotated by replacing a file on the host.
    assert "trupryce-data-platform-vps.key" not in dockerfile
    assert "/etc/trupryce" not in dockerfile


def test_no_committed_infrastructure_file_carries_key_material() -> None:
    # Assignment shape, not name mention. `AWS_ACCESS_KEY_ID=AKIA...` is a leak;
    # a comment stating that no such variable exists is the opposite of one, and
    # a guard that cannot tell them apart gets weakened the first time it fires.
    assigned = re.compile(
        r"(AWS_ACCESS_KEY_ID|AWS_SECRET_ACCESS_KEY|repo1-cipher-pass)\s*[=:]\s*\S"
    )
    pem = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
    for path in sorted(INFRA_ROOT.rglob("*")):
        if not path.is_file() or ".env" in path.name:
            continue
        code = code_lines(path)
        match = assigned.search(code)
        assert match is None, f"{path} assigns {match.group(1) if match else ''}"
        # Checked against raw text: a PEM block is unmistakable and a `#` inside
        # base64 must not let one hide behind comment stripping.
        raw = path.read_text(encoding="utf-8", errors="ignore")
        assert pem.search(raw) is None, f"{path} contains private key material"


def test_pgbackrest_configuration_is_keyless_and_carries_no_passphrase() -> None:
    settings = [
        line.strip()
        for line in PGBACKREST_CONF.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert "repo1-s3-key-type=process" in settings
    assert "repo1-s3-process-cmd=/usr/local/bin/pgbackrest-aws-signing" in settings
    # The option pgBackRest 2.59.1 actually defines is `repo-s3-process-cmd`.
    # `repo1-s3-key-process` is not an alias; it is silently dropped with a
    # warning, which is why the string assertion alone was not enough and why
    # test_built_image_parses_the_committed_configuration exists.
    assert not any(s.startswith("repo1-s3-key-process") for s in settings)
    assert "repo1-cipher-type=aes-256-cbc" in settings
    assert "repo1-retention-full=4" in settings
    assert "repo1-retention-full-type=count" in settings
    assert "repo1-s3-bucket=trupryce-property-tax-backups" in settings
    assert "repo1-path=/pgbackrest/platform" in settings
    # Asserted over settings rather than the whole file, so the comment that
    # explains where the passphrase comes from is not mistaken for the
    # passphrase being here. Only an assignment would leak it.
    assert not any(setting.startswith("repo1-cipher-pass") for setting in settings)
    assert not any(setting.startswith("repo1-s3-key=") for setting in settings)
    assert not any(setting.startswith("repo1-s3-key-secret") for setting in settings)


def test_cipher_passphrase_reaches_pgbackrest_only_through_bitwarden() -> None:
    compose = COMPOSE_FILE.read_text(encoding="utf-8")
    environment = load_compose()["services"]["postgres"]["environment"]
    assert (
        environment["PGBACKREST_REPO1_CIPHER_PASS"]
        == "${PGBACKREST_CIPHER_PASS:?PGBACKREST_CIPHER_PASS is required}"
    )
    # The existing boundary is unchanged: the Bitwarden access token still
    # reaches no container, so a backup secret does not become a way in.
    assert "BWS_ACCESS_TOKEN" not in compose


def test_credential_wrapper_execs_the_helper_and_never_handles_the_response() -> None:
    wrapper = CREDENTIAL_WRAPPER.read_text(encoding="utf-8")
    assert "set -euo pipefail" in wrapper
    assert "exec aws_signing_helper credential-process" in wrapper
    code = "\n".join(line for line in wrapper.splitlines() if not line.lstrip().startswith("#"))
    # Parsing, caching, or logging the response turns a clear "expired
    # certificate" into an empty-credential failure inside pgBackRest. exec also
    # makes the helper's exit status the wrapper's, so a failure is visible.
    for forbidden in ("jq", "python", "tee", "cat ", "logger", ">>", "mktemp"):
        assert forbidden not in code, forbidden
    assert code.count("exec ") == 1


def test_backup_script_selects_the_container_by_compose_label() -> None:
    script = BACKUP_SCRIPT.read_text(encoding="utf-8")
    assert "label=com.docker.compose.project=${COMPOSE_PROJECT}" in script
    assert "label=com.docker.compose.service=${COMPOSE_SERVICE}" in script
    # `docker compose build` writes project and service labels into the IMAGE,
    # so every container started from it inherits them -- an isolated PITR
    # restore included. Only a container Compose actually ran carries oneoff,
    # and without it the selector matched two candidates during the recorded
    # restore exercise.
    assert "label=com.docker.compose.oneoff=False" in script
    # A container ID changes on every recreate, so a unit pinned to one keeps
    # running and protects nothing the first time the stack is rebuilt.
    assert "docker ps --quiet" in script
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
    assert "--filter name=" not in code
    assert "refusing to guess" in script


def test_backup_scheduling_does_not_depend_on_the_orchestrator_it_protects() -> None:
    directives = ("After", "Before", "Requires", "Requisite", "Wants", "BindsTo", "PartOf")
    units = sorted(SYSTEMD_ROOT.glob("pgbackrest-*"))
    assert {unit.name for unit in units} == {
        "pgbackrest-full.service.template",
        "pgbackrest-full.timer",
        "pgbackrest-diff.service.template",
        "pgbackrest-diff.timer",
    }
    for unit in units:
        for line in unit.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(directives) and "=" in stripped:
                # Checked on directives only: the units carry a comment saying
                # why Airflow is deliberately absent, and that comment naming
                # Airflow must not read as a dependency on it.
                assert "airflow" not in stripped.split("=", 1)[1].lower(), unit.name
    for unit in ("pgbackrest-full.service.template", "pgbackrest-diff.service.template"):
        body = (SYSTEMD_ROOT / unit).read_text(encoding="utf-8")
        assert "infra/scripts/pgbackrest-backup.sh" in body
    for timer in ("pgbackrest-full.timer", "pgbackrest-diff.timer"):
        body = (SYSTEMD_ROOT / timer).read_text(encoding="utf-8")
        # Without Persistent a backup missed while the host was down is simply
        # skipped, which is how a retention window silently loses its base.
        assert "Persistent=true" in body


PGBACKREST_PROBE_IMAGE = "property-tax-postgres:config-probe"


def build_probe_image() -> None:
    subprocess.run(
        [
            "docker",
            "build",
            "-q",
            "-f",
            str(INFRA_ROOT / "postgres" / "Dockerfile"),
            "-t",
            PGBACKREST_PROBE_IMAGE,
            str(REPOSITORY_ROOT),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=1800,
    )


def parse_committed_configuration() -> str:
    """Run the pinned pgBackRest against the committed config and return its output.

    `help` parses the configuration file fully but reaches neither PostgreSQL nor
    S3, so this is deterministic and needs no credential.
    """
    build_probe_image()
    completed = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            PGBACKREST_PROBE_IMAGE,
            "pgbackrest",
            "--stanza=platform",
            "help",
            "backup",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    return completed.stdout + completed.stderr


@pytest.mark.skipif(shutil.which("docker") is None, reason="requires docker to build the image")
def test_built_image_parses_the_committed_configuration() -> None:
    """The gate that catches a misspelled pgBackRest option.

    pgBackRest treats an unknown option in a configuration *file* as a warning
    and continues, so the option is silently dropped and the repository ends up
    with no way to authenticate. Exit status is 0 either way, which is why this
    asserts on the warning text and on the resolved option set rather than on
    the return code. A string assertion over the file cannot catch it at all:
    `repo1-s3-key-process` is a perfectly well-formed line that pgBackRest does
    not implement.
    """
    output = parse_committed_configuration()
    assert "invalid option" not in output, output
    assert "invalid value" not in output, output
    # Present in the options pgBackRest actually resolved, not merely in the file.
    assert "--repo1-s3-process-cmd=/usr/local/bin/pgbackrest-aws-signing" in output, output
    assert "--repo1-s3-key-type=process" in output, output
    assert "--repo1-cipher-type=aes-256-cbc" in output, output


@pytest.mark.skipif(shutil.which("docker") is None, reason="requires docker to build the image")
def test_pinned_binary_defines_the_process_command_option() -> None:
    """`repo-s3-process-cmd` is the real option name; the other spelling is not an alias."""
    build_probe_image()
    completed = subprocess.run(
        ["docker", "run", "--rm", PGBACKREST_PROBE_IMAGE, "pgbackrest", "help", "backup"],
        check=False,
        capture_output=True,
        text=True,
        timeout=300,
    )
    catalogue = completed.stdout + completed.stderr
    assert "--repo-s3-process-cmd" in catalogue
    assert "--repo-s3-key-process" not in catalogue


CERTIFICATE_DIR = Path(os.environ.get("TRUPRYCE_AWS_CERTIFICATE_DIR", "/etc/trupryce/aws"))
WORKLOAD_KEY = CERTIFICATE_DIR / "trupryce-data-platform-vps.key"


def certificate_gid() -> str:
    values = parse_environment_file(INFRA_ROOT / ".env.example")
    return values["TRUPRYCE_AWS_GID"]


def test_postgres_joins_the_certificate_group_to_read_the_workload_key() -> None:
    """`:ro` gives immutability, not readability.

    The container's postgres user is uid 999 and the host key is owned by the
    operator at 0640, so without a shared group `archive_command` fails at
    runtime with a permission error that no static check would surface.
    """
    postgres = load_compose()["services"]["postgres"]
    assert postgres["group_add"] == ["${TRUPRYCE_AWS_GID:-2000}"]
    assert certificate_gid().isdigit()
    # Numeric, because the group has no name inside the image; a name would
    # resolve to nothing and the supplementary group would silently not apply.
    mounts = [entry for entry in postgres["volumes"] if "/etc/trupryce/aws" in entry]
    assert mounts == ["${TRUPRYCE_AWS_CERTIFICATE_DIR:-/etc/trupryce/aws}:/etc/trupryce/aws:ro"]


@pytest.mark.skipif(not WORKLOAD_KEY.exists(), reason="requires the host workload key")
def test_workload_key_is_group_readable_but_never_world_readable() -> None:
    mode = stat.S_IMODE(WORKLOAD_KEY.stat().st_mode)
    assert mode & 0o007 == 0, f"key is world-accessible: {mode:o}"
    assert mode & 0o040, f"key is not group-readable, so postgres cannot read it: {mode:o}"
    assert mode & 0o002 == 0, f"key is world-writable: {mode:o}"
    assert WORKLOAD_KEY.stat().st_gid == int(certificate_gid())
    directory = stat.S_IMODE(CERTIFICATE_DIR.stat().st_mode)
    assert directory & 0o007 == 0, f"certificate directory is world-accessible: {directory:o}"
    # 0o050 = group r-x; without execute the group cannot traverse into the
    # directory and the key's own group bit is unreachable.
    assert directory & 0o050 == 0o050, f"group cannot traverse the directory: {directory:o}"


@pytest.mark.skipif(
    shutil.which("docker") is None or not WORKLOAD_KEY.exists(),
    reason="requires docker and the host workload key",
)
def test_only_the_certificate_group_can_read_the_key_from_a_container() -> None:
    """Group membership is the authorization boundary, not file mode alone.

    `postgres` reaches the key through the certificate group it belongs to in
    the image. Any identity outside that group must not, which is what keeps
    0640 meaningful: the key is readable by a named group and by nobody else.
    """
    build_probe_image()

    def readable(user: str) -> bool:
        return (
            subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-v",
                    f"{CERTIFICATE_DIR}:/etc/trupryce/aws:ro",
                    "--user",
                    user,
                    PGBACKREST_PROBE_IMAGE,
                    "test",
                    "-r",
                    "/etc/trupryce/aws/trupryce-data-platform-vps.key",
                ],
                capture_output=True,
                timeout=300,
            ).returncode
            == 0
        )

    assert readable("postgres"), "postgres cannot read the key; archiving would fail"
    # An arbitrary uid with no group membership: the world bits are what would
    # let this through, and they are not set.
    assert not readable("12345:12345"), "key is readable outside the certificate group"


def test_reported_secret_count_matches_what_is_actually_written(tmp_path: Path) -> None:
    """The reported count drifted to nine when the tenth secret was added.

    Asserted against the file the run produced rather than against a literal, so
    adding the eleventh secret cannot reintroduce the same defect. Only names and
    counts are read here; no generated value is compared, printed, or retained.
    """
    output = tmp_path / "runtime-secrets.env"
    completed = subprocess.run(
        [str(INFRA_ROOT / "scripts" / "generate-runtime-secrets.sh"), "--write", str(output)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
    written = parse_environment_file(output)
    assert set(written) == SECRET_VARIABLES
    assert f"wrote {len(written)} secrets" in completed.stderr
    assert "wrote 9 secrets" not in completed.stderr
    generator = (INFRA_ROOT / "scripts" / "generate-runtime-secrets.sh").read_text(encoding="utf-8")
    assert "nine" not in generator.lower()


def test_unit_definitions_carry_no_host_specific_identity() -> None:
    """A durable unit must survive a rebuild onto a different host.

    A hard-coded operator account or home directory produces a timer that
    installs fine and then fails at its first fire on the replacement VPS --
    silently, because a timer whose service cannot start is not a visible
    outage. The placeholders are resolved by the install script instead.
    """
    templates = sorted(SYSTEMD_ROOT.glob("*.service.template"))
    assert templates, "no unit templates found"
    for template in templates:
        body = template.read_text(encoding="utf-8")
        assert "@@SERVICE_USER@@" in body
        assert "@@REPOSITORY_DIR@@" in body
        assert "@@DOCKER_GROUP@@" in body
        for host_specific in ("/home/", "User=mike", "/Users/"):
            assert host_specific not in body, f"{template.name} hard-codes {host_specific}"
        # Least privilege is part of the durable definition, not the install.
        assert "NoNewPrivileges=true" in body
        assert "ProtectSystem=strict" in body
    for timer in sorted(SYSTEMD_ROOT.glob("*.timer")):
        body = timer.read_text(encoding="utf-8")
        assert "/home/" not in body, f"{timer.name} hard-codes a home directory"


def test_install_script_resolves_every_placeholder_and_fails_closed() -> None:
    script = (INFRA_ROOT / "scripts" / "install-systemd-units.sh").read_text(encoding="utf-8")
    assert "set -euo pipefail" in script
    for placeholder in ("@@SERVICE_USER@@", "@@DOCKER_GROUP@@", "@@REPOSITORY_DIR@@"):
        assert placeholder in script, placeholder
    # An unsubstituted placeholder must stop the install rather than become a
    # unit that fails once a week.
    assert "unsubstituted placeholder" in script
    # Docker access is verified, never granted: membership of the docker group is
    # root-equivalent, so it is an operator decision rather than a side effect of
    # installing a timer.
    assert "usermod" not in script, "install script grants Docker access instead of checking it"
    assert "could not reach the Docker socket" in script
    # The certificate group contract comes from the shared helper, so this
    # installer and install-certificate-identity.sh cannot disagree about what
    # the configured GID means.
    assert "lib/certificate-group.sh" in script
    assert "require_certificate_group" in script


RESTORE_SCRIPT = INFRA_ROOT / "scripts" / "pgbackrest-restore.sh"


def shell_command_lines(markdown: str) -> list[str]:
    """Lines inside ```bash / ```sh fences, excluding comments.

    Documentation guards must assert on what a reader would *run*, not on what
    the document *says*. Prose explaining why an option is wrong necessarily
    contains that option, and a guard that reads the explanation as an
    instruction makes clear writing fail the build.
    """
    lines: list[str] = []
    in_shell_fence = False
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            in_shell_fence = stripped[3:].strip() in {"bash", "sh", "shell"}
            continue
        if in_shell_fence and stripped and not stripped.startswith("#"):
            lines.append(line)
    return lines


def test_restore_never_targets_the_production_volume() -> None:
    script = RESTORE_SCRIPT.read_text(encoding="utf-8")
    assert "set -euo pipefail" in script
    # Refused by name and again by Compose label: a caller could pass a
    # differently named volume that Compose still owns.
    assert "refusing to restore over the production volume" in script
    assert "refusing to restore into a Compose-managed volume" in script
    assert "com.docker.compose.project" in script
    # Loopback only. A recovered cluster holds production data at some past
    # state and must not be reachable from the tailnet.
    assert 'bind_address="127.0.0.1"' in script


def test_restore_passes_the_passphrase_by_reference_not_in_argv() -> None:
    script = RESTORE_SCRIPT.read_text(encoding="utf-8")
    code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
    # `-e NAME` takes the value from the environment; `-e NAME=value` puts the
    # passphrase into argv, where it reaches shell history and `ps` output.
    assert "-e PGBACKREST_REPO1_CIPHER_PASS\n" in code or "-e PGBACKREST_REPO1_CIPHER_PASS " in code
    assert "-e PGBACKREST_REPO1_CIPHER_PASS=" not in code
    assert '-e "PGBACKREST_REPO1_CIPHER_PASS=' not in code
    # The Bitwarden access token is read on the host and never exported onward.
    assert "BWS_ACCESS_TOKEN=" in code
    assert "-e BWS_ACCESS_TOKEN" not in code
    assert "bws run" in code


def test_restore_gives_the_recovered_cluster_what_archive_get_needs() -> None:
    """Recovery to a timestamp runs `pgbackrest archive-get` during startup.

    A recovered container given only the restored volume replays the base backup,
    fails to fetch WAL, and stops short of the target while looking successful.
    """
    script = RESTORE_SCRIPT.read_text(encoding="utf-8")
    # One argument array, reused for both the restore and the started cluster,
    # so the two cannot drift apart.
    assert "identity_arguments=(" in script
    started = script.split("docker run -d --init --name")[1]
    assert '"${identity_arguments[@]}"' in started
    assert "/etc/trupryce/aws:ro" in script
    assert "--group-add" in script
    for arn in (
        "TRUPRYCE_AWS_TRUST_ANCHOR_ARN",
        "TRUPRYCE_AWS_PROFILE_ARN",
        "TRUPRYCE_AWS_ROLE_ARN",
    ):
        assert arn in script, arn


def test_runbook_never_teaches_a_literal_passphrase_command() -> None:
    runbook = (REPOSITORY_ROOT / "docs" / "operations" / "postgresql-recovery.md").read_text(
        encoding="utf-8"
    )
    for line in runbook.splitlines():
        if "PGBACKREST_REPO1_CIPHER_PASS=" in line:
            # The single permitted occurrence is the labelled counter-example.
            assert "<the-passphrase>" in line, line
    assert "Never do this" in runbook
    # Administrator commands must name the administrator profile explicitly
    # rather than relying on ambient credentials.
    for verb in (
        "iam create-role",
        "rolesanywhere create-profile",
        "s3api create-bucket",
        "iam put-role-policy",
        "s3api put-bucket",
        "s3api put-public-access-block",
    ):
        for line in shell_command_lines(runbook):
            if verb in line and line.strip().startswith("aws"):
                assert "--profile boss" in line, line
    # us-east-1 rejects an explicit LocationConstraint of us-east-1. Asserted
    # over executable command lines only: the prose that explains why it must be
    # omitted necessarily names it, and a guard that cannot tell an instruction
    # from an explanation punishes the documentation for being clear.
    for line in shell_command_lines(runbook):
        assert "LocationConstraint=us-east-1" not in line, line
    # Anchored to the create-profile invocation itself. A profile created
    # without --enabled exists, lists, and refuses every credential exchange,
    # so a document-wide substring check would pass while the procedure is
    # broken. The command spans continuation lines, so the whole block is joined
    # before asserting.
    commands = " ".join(shell_command_lines(runbook))
    create_profile = commands.split("rolesanywhere create-profile", 1)
    assert len(create_profile) == 2, "runbook does not create a Roles Anywhere profile"
    following = create_profile[1].split("aws ", 1)[0]
    assert "--enabled" in following, following
    # The VPS-local data profile is trupryce-data-vps; trupryce-vps is wrong.
    assert "trupryce-data-vps" in runbook
    assert "profile trupryce-vps]" not in runbook
    assert "--profile trupryce-vps" not in runbook


def test_certificate_expiry_check_exists_and_claims_no_automation() -> None:
    script = (INFRA_ROOT / "scripts" / "check-certificate-expiry.sh").read_text(encoding="utf-8")
    assert "set -euo pipefail" in script
    assert "openssl x509" in script
    # Honest about what it is: a signal, not monitoring.
    assert "not monitoring" in script
    runbook = (REPOSITORY_ROOT / "docs" / "operations" / "postgresql-recovery.md").read_text(
        encoding="utf-8"
    )
    assert "check-certificate-expiry.sh" in runbook
    assert "2026-11-17" in runbook
    assert "Nothing alerts on this" in runbook


def test_container_environment_does_not_squat_the_pgbackrest_namespace() -> None:
    """pgBackRest parses every `PGBACKREST_*` variable as one of its own options.

    An identity variable named `PGBACKREST_AWS_CERTIFICATE` is therefore read as
    the option `aws-certificate`, rejected as invalid, and warned about on every
    single command -- while still being visible to the wrapper, so nothing fails
    outright and the warnings look cosmetic. Anything that is not a real
    pgBackRest option belongs outside the namespace.
    """
    # Real pgBackRest options this deployment sets through the environment.
    permitted = {"PGBACKREST_REPO1_CIPHER_PASS", "PGBACKREST_STANZA"}
    environment = load_compose()["services"]["postgres"]["environment"]
    squatters = {
        name for name in environment if name.startswith("PGBACKREST_") and name not in permitted
    }
    assert not squatters, f"not pgBackRest options: {sorted(squatters)}"
    # The identity variables live under the project's own prefix instead.
    for name in (
        "TRUPRYCE_AWS_CERTIFICATE",
        "TRUPRYCE_AWS_PRIVATE_KEY",
        "TRUPRYCE_AWS_TRUST_ANCHOR_ARN",
        "TRUPRYCE_AWS_PROFILE_ARN",
        "TRUPRYCE_AWS_ROLE_ARN",
    ):
        assert name in environment, name


def test_pgbackrest_connects_as_the_clusters_actual_superuser() -> None:
    """The image's OS user is `postgres`; this cluster's superuser is not.

    Without pg1-user, pgBackRest connects as the OS user it runs as and fails
    with `role "postgres" does not exist`, which reads like a pgBackRest fault
    rather than a mismatch with the superuser name this deployment chose.
    """
    settings = [
        line.strip()
        for line in PGBACKREST_CONF.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert "pg1-user=platform_admin" in settings
    bootstrap = (INFRA_ROOT / "postgres" / "init" / "10-create-runtime-databases.sh").read_text(
        encoding="utf-8"
    )
    compose_user = load_compose()["services"]["postgres"]["environment"]["POSTGRES_USER"]
    # Tied to the Compose value, so renaming the superuser cannot leave
    # pgbackrest.conf pointing at a role that no longer exists.
    assert compose_user == "platform_admin", compose_user
    assert bootstrap  # bootstrap creates the other roles; the superuser comes from Compose


def test_restore_container_cannot_masquerade_as_the_production_service() -> None:
    """The restore container must not answer a production label selector.

    It is started from the Compose-built image, so it inherits that image's
    project and service labels. Left alone, the backup timers' own selector
    would see two candidates while a restore is running.
    """
    script = RESTORE_SCRIPT.read_text(encoding="utf-8")
    assert "--label com.docker.compose.project=pitr-verify" in script
    assert "--label com.docker.compose.service=pitr-verify" in script
    assert "--label com.docker.compose.oneoff=True" in script


def test_restore_waits_for_promotion_rather_than_readiness() -> None:
    """`pg_isready` reports OK while the cluster is still replaying WAL.

    Asserting recovery state at that moment finds pg_is_in_recovery() true and
    reports a failed recovery for a restore that was merely still running.
    """
    script = RESTORE_SCRIPT.read_text(encoding="utf-8")
    assert "SELECT pg_is_in_recovery()" in script
    assert "did not finish recovery and promote" in script
    # An assertion block that silently produces nothing must fail, not pass.
    assert "refusing to report a passing exercise" in script
    # -c, not a heredoc: `docker exec` without -i has no stdin, so a heredoc
    # reaches psql empty and every assertion prints nothing.
    assert "<<'SQL'" not in script


def test_image_grants_postgres_the_certificate_group() -> None:
    """Compose `group_add` does not survive the entrypoint's switch to postgres.

    The postgres entrypoint starts as root and re-derives supplementary groups
    from the image's /etc/group, dropping anything Docker added. `docker exec
    --user postgres` keeps the added group, so every hand-run check passes while
    the archiver -- a child of the postmaster -- runs without it, cannot read the
    key. The resulting failure presents as cluster restarts rather than archive
    errors, because pgBackRest's daemonized async worker is orphaned onto PID 1
    -- the postmaster -- whose nonzero exit is reaped as an unrecognised server
    process. An ordinary nonzero archive_command exit is merely retried.
    """
    dockerfile = (INFRA_ROOT / "postgres" / "Dockerfile").read_text(encoding="utf-8")
    assert "groupadd --gid" in dockerfile
    assert "usermod --append --groups trupryce-certificates postgres" in dockerfile
    assert "ARG TRUPRYCE_AWS_GID" in dockerfile
    # Image and host must agree on the number, so Compose passes it as a build arg.
    build_args = load_compose()["services"]["postgres"]["build"]["args"]
    assert build_args["TRUPRYCE_AWS_GID"] == "${TRUPRYCE_AWS_GID:-2000}"


@pytest.mark.skipif(
    shutil.which("docker") is None or not WORKLOAD_KEY.exists(),
    reason="requires docker and the host workload key",
)
def test_postmaster_children_can_read_the_key_without_docker_group_add() -> None:
    """The case that actually broke: no --group-add, as the archiver runs."""
    build_probe_image()
    completed = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{CERTIFICATE_DIR}:/etc/trupryce/aws:ro",
            "--user",
            "postgres",
            PGBACKREST_PROBE_IMAGE,
            "test",
            "-r",
            "/etc/trupryce/aws/trupryce-data-platform-vps.key",
        ],
        capture_output=True,
        timeout=300,
    )
    assert completed.returncode == 0, (
        "postgres cannot read the key from image group membership alone; "
        "the archiver would fail at runtime"
    )


IDENTITY_INSTALLER = INFRA_ROOT / "scripts" / "install-certificate-identity.sh"
IDENTITY_FILE = CERTIFICATE_DIR / "identity.env"


def test_identity_installer_derives_values_and_admits_no_secret() -> None:
    """The async worker's identity file must be reproducible on a clean host.

    It is derived from infra/.env rather than hand-written, so an ARN has one
    home and no duplicate to drift, and it carries only non-secret values: the
    passphrase, the Bitwarden token, and AWS credentials are all obtained
    elsewhere and would be readable by the whole certificate group if written
    here.
    """
    script = IDENTITY_INSTALLER.read_text(encoding="utf-8")
    assert "set -euo pipefail" in script
    for key in (
        "TRUPRYCE_AWS_CERTIFICATE",
        "TRUPRYCE_AWS_PRIVATE_KEY",
        "TRUPRYCE_AWS_TRUST_ANCHOR_ARN",
        "TRUPRYCE_AWS_PROFILE_ARN",
        "TRUPRYCE_AWS_ROLE_ARN",
    ):
        assert key in script, key
    # Derived, not duplicated.
    assert "read_configuration_value" in script
    assert "$infra_dir/.env" in script
    # Refuses to write anything secret-shaped.
    for forbidden in ("PGBACKREST_CIPHER_PASS", "BWS_ACCESS_TOKEN", "AWS_SECRET_ACCESS_KEY"):
        assert forbidden in script, f"{forbidden} is not guarded against"
    assert "refusing to write" in script
    # The permission contract lives here too, and fails closed.
    assert "chmod 0640" in script and "chmod 0750" in script
    assert "world-accessible" in script


@pytest.mark.skipif(not IDENTITY_FILE.exists(), reason="requires the host identity file")
def test_installed_identity_file_holds_no_secret_and_matches_the_contract() -> None:
    mode = stat.S_IMODE(IDENTITY_FILE.stat().st_mode)
    assert mode & 0o007 == 0, f"identity file is world-accessible: {mode:o}"
    assert mode & 0o040, f"identity file is not group-readable: {mode:o}"
    assert IDENTITY_FILE.stat().st_gid == int(certificate_gid())

    assignments = {
        line.split("=", 1)[0].strip()
        for line in IDENTITY_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#") and "=" in line
    }
    assert assignments == {
        "TRUPRYCE_AWS_CERTIFICATE",
        "TRUPRYCE_AWS_PRIVATE_KEY",
        "TRUPRYCE_AWS_TRUST_ANCHOR_ARN",
        "TRUPRYCE_AWS_PROFILE_ARN",
        "TRUPRYCE_AWS_ROLE_ARN",
    }
    # Asserted over assignments, not raw text: the file's own comment states
    # that it holds no token, and a substring check would read that as one.
    for name in assignments:
        assert not any(marker in name for marker in ("CIPHER", "TOKEN", "SECRET", "ACCESS_KEY")), (
            name
        )


def test_documentation_does_not_overclaim_the_recovery_point() -> None:
    """`archive_timeout` bounds an idle segment switch, not durable RPO.

    Archive failure or backlog puts the real recovery point arbitrarily far
    behind the configured interval, which is exactly the gap the unimplemented
    observability requirement has to alert on. Documentation that calls the
    interval a guarantee would report five minutes while nothing had reached S3
    for a day.
    """
    sources = [
        REPOSITORY_ROOT / "docs" / "operations" / "postgresql-recovery.md",
        REPOSITORY_ROOT
        / "docs"
        / "decisions"
        / "0010-replaceable-local-storage-and-s3-backup-repository.md",
        REPOSITORY_ROOT
        / "openspec"
        / "changes"
        / "add-postgresql-recovery-foundation"
        / "design.md",
        REPOSITORY_ROOT
        / "openspec"
        / "changes"
        / "add-postgresql-recovery-foundation"
        / "proposal.md",
        COMPOSE_FILE,
    ]
    overclaims = (
        "bounds the recovery point",
        "bounding the recovery point",
        "RPO bounded",
        "bounded at 300",
        "wall-clock guarantee",
    )
    for source in sources:
        text = source.read_text(encoding="utf-8")
        for phrase in overclaims:
            assert phrase not in text, f"{source.name} claims {phrase!r}"

    # The configuration itself is unchanged: only the claim about it moved.
    assert "archive_timeout=300" in postgres_command()


def test_archive_failure_mechanism_is_stated_accurately() -> None:
    """An ordinary nonzero archive_command exit is retried, not fatal.

    The restart came from pgBackRest's daemonized async worker being orphaned
    onto PID 1 -- the postmaster -- and reaped as an unrecognised server
    process. Documenting the simpler, wrong version sends an operator looking
    for a signal source that does not exist.
    """
    runbook = (REPOSITORY_ROOT / "docs" / "operations" / "postgresql-recovery.md").read_text(
        encoding="utf-8"
    )
    design = (
        REPOSITORY_ROOT
        / "openspec"
        / "changes"
        / "add-postgresql-recovery-foundation"
        / "design.md"
    ).read_text(encoding="utf-8")
    for text in (runbook, design):
        assert "reparent" in text.lower() or "orphan" in text.lower()
        assert "PID 1" in text
        assert "retried" in text or "retries" in text
    for source in (runbook, design, (INFRA_ROOT / "postgres" / "Dockerfile").read_text("utf-8")):
        assert "treats the dead archive command as a backend crash" not in source


def test_postgres_is_not_pid_one() -> None:
    """A backup failure must not become a database availability failure.

    `archive-async` daemonizes a pgBackRest worker; a daemonized worker is
    orphaned, and an orphan is reparented to PID 1. With PostgreSQL as PID 1 the
    postmaster reaps a child it never forked, treats the nonzero exit as a
    crashed backend, and runs full crash recovery. An init process as PID 1
    reaps orphans instead, so archiving can fail and be repaired without
    restarting the database.
    """
    assert load_compose()["services"]["postgres"]["init"] is True
    # The isolated recovery cluster runs archive-get during startup and has the
    # same exposure, so it gets the same treatment.
    restore = RESTORE_SCRIPT.read_text(encoding="utf-8")
    assert "docker run -d --init --name" in restore
    assert "docker run --rm --init" in restore


def test_installers_share_one_fail_closed_certificate_group_contract() -> None:
    """Adopting an existing GID is a silent privilege leak.

    Debian and Ubuntu hand out 1000+ to ordinary user groups, so the configured
    GID may already be `developers`. Accepting it and then chgrp-ing the Roles
    Anywhere private key to 0640 grants every member of an unrelated group the
    ability to assume the platform's AWS identity.
    """
    helper = (INFRA_ROOT / "scripts" / "lib" / "certificate-group.sh").read_text(encoding="utf-8")
    assert "require_certificate_group" in helper
    assert "already belongs to group" in helper
    assert "refusing to grant private-key access to an unrelated group" in helper
    # Name and number must agree in both directions.
    assert "but the configuration says" in helper

    for installer in ("install-certificate-identity.sh", "install-systemd-units.sh"):
        script = (INFRA_ROOT / "scripts" / installer).read_text(encoding="utf-8")
        assert "lib/certificate-group.sh" in script, installer
        assert "require_certificate_group" in script, installer
        # The naive form must not survive anywhere.
        code = "\n".join(line for line in script.splitlines() if not line.lstrip().startswith("#"))
        assert "groupadd --gid" not in code, f"{installer} still creates a group directly"


def test_backup_units_do_not_use_conflicts_as_a_mutex() -> None:
    """`Conflicts=` stops the other unit; it is not a lock and does not wait.

    With a daily differential and a weekly full, any Sunday full still running
    at the differential's start time would be terminated mid-backup -- and the
    full is the base every restore in the retention window depends on. The
    longer it takes, the more there is to lose, and the likelier it is to be
    destroyed.
    """
    for unit in sorted(SYSTEMD_ROOT.glob("*.service.template")):
        for line in unit.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("Conflicts=") and "pgbackrest" in stripped:
                raise AssertionError(
                    f"{unit.name} uses Conflicts= between backup units: {stripped}"
                )

    full_timer = (SYSTEMD_ROOT / "pgbackrest-full.timer").read_text(encoding="utf-8")
    diff_timer = (SYSTEMD_ROOT / "pgbackrest-diff.timer").read_text(encoding="utf-8")
    assert "OnCalendar=Sun " in full_timer
    # Mon-Sat: the two never contend on schedule, however long the full runs.
    assert "OnCalendar=Mon,Tue,Wed,Thu,Fri,Sat " in diff_timer
    assert "*-*-* 03:30:00" in diff_timer
    # Ordering is still declared for the Persistent=true catch-up case, where
    # both may be queued in one transaction and the full must go first.
    diff_service = (SYSTEMD_ROOT / "pgbackrest-diff.service.template").read_text(encoding="utf-8")
    assert "After=pgbackrest-full.service" in diff_service


def test_host_signing_helper_is_installable_and_pinned() -> None:
    """`~/.aws/config` invokes the helper on the HOST, not the one in the image.

    Without it every `aws --profile trupryce-backup ...` command fails on a
    fresh server, including the isolation checks that gate the rest of the
    bootstrap.
    """
    script = (INFRA_ROOT / "scripts" / "install-signing-helper.sh").read_text(encoding="utf-8")
    assert "set -euo pipefail" in script
    assert "SIGNING_HELPER_VERSION:-1.8.4" in script
    assert "sha256sum -c -" in script
    assert "checksum mismatch; refusing to install" in script
    # A digest is architecture-specific; refuse rather than install unverified.
    assert "no pinned digest for" in script


def test_clean_host_procedure_orders_identity_before_archiving() -> None:
    """The runbook must be executable top to bottom on a new host."""
    runbook = (REPOSITORY_ROOT / "docs" / "operations" / "postgresql-recovery.md").read_text(
        encoding="utf-8"
    )
    # Host prerequisites come before the step that starts PostgreSQL archiving.
    prerequisites = runbook.index("### 2.1 Host prerequisites")
    enable_archiving = runbook.index("### 2.3 Enable archiving")
    assert prerequisites < enable_archiving

    identity_install = runbook.index("install-certificate-identity.sh")
    assert identity_install < enable_archiving, (
        "identity installation is documented after the restart that needs it"
    )

    # Every host-bootstrap step the procedure depends on is named in it.
    for step in (
        "install-signing-helper.sh",
        "bootstrap-env.sh",
        "install-certificate-identity.sh",
        "install-systemd-units.sh",
        "trupryce-data-platform-hostinger",
    ):
        assert step in runbook, step
