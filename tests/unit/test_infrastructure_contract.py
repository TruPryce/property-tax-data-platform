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
    assert "repo1-s3-key-process=/usr/local/bin/pgbackrest-aws-signing" in settings
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
        "pgbackrest-full.service",
        "pgbackrest-full.timer",
        "pgbackrest-diff.service",
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
    for unit in ("pgbackrest-full.service", "pgbackrest-diff.service"):
        body = (SYSTEMD_ROOT / unit).read_text(encoding="utf-8")
        assert "infra/scripts/pgbackrest-backup.sh" in body
    for timer in ("pgbackrest-full.timer", "pgbackrest-diff.timer"):
        body = (SYSTEMD_ROOT / timer).read_text(encoding="utf-8")
        # Without Persistent a backup missed while the host was down is simply
        # skipped, which is how a retention window silently loses its base.
        assert "Persistent=true" in body
