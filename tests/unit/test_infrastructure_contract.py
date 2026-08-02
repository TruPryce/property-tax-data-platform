from __future__ import annotations

import base64
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest
import yaml

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
INFRA_ROOT = REPOSITORY_ROOT / "infra"
COMPOSE_FILE = INFRA_ROOT / "compose.yaml"
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
}


def load_compose() -> dict[str, object]:
    document = yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


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
    assert "verified 9 secrets" in completed.stderr

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
    bitwarden_environment_file.write_text(
        "BWS_ACCESS_TOKEN=test-access-token\nBWS_PROJECT_ID=test-project-id\n", encoding="utf-8"
    )
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
    bitwarden_environment_file.write_text(
        "BWS_ACCESS_TOKEN=test-access-token\nBWS_PROJECT_ID=test-project-id\n", encoding="utf-8"
    )
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
