#!/usr/bin/env bash
set -Eeuo pipefail

# Generates every runtime secret value the Compose topology requires: one per
# entry in SECRET_NAMES plus the Fernet key, which is generated differently.
#
# Values are alphanumeric apart from the Fernet key. That is not decoration:
# Compose interpolates AIRFLOW_DB_PASSWORD into a SQLAlchemy URL, where a
# generator's default punctuation silently reparses the host and password, while
# the PostgreSQL bootstrap quotes the same value safely. The remaining values
# reach Airflow as plain environment variables or quoted arguments, so a single
# alphabet keeps every value safe in every position at the cost of nothing but
# length.
#
#   ./infra/scripts/generate-runtime-secrets.sh
#       Print `NAME=value` lines for manual entry into the Bitwarden project.
#
#   ./infra/scripts/generate-runtime-secrets.sh --write PATH
#       Write those lines to a new mode-0600 file instead.
#
#   BWS_ACCESS_TOKEN=... ./infra/scripts/generate-runtime-secrets.sh --bws PROJECT_ID
#       Create the secrets directly in a Bitwarden Secrets Manager project. This
#       needs a machine account with write access, which is deliberately not the
#       read-only account the runtime wrapper uses.

SECRET_NAMES=(
  POSTGRES_SUPERUSER_PASSWORD
  AIRFLOW_DB_PASSWORD
  PROPERTY_TAX_MIGRATOR_PASSWORD
  PROPERTY_TAX_INGESTION_PASSWORD
  PROPERTY_TAX_API_PASSWORD
  AIRFLOW_API_SECRET_KEY
  AIRFLOW_JWT_SECRET
  AIRFLOW_ADMIN_PASSWORD
  # pgBackRest repository encryption. Recovery-critical rather than
  # access-critical: rotating it does not re-encrypt existing backups, and
  # losing it makes every backup already in S3 permanently unreadable.
  PGBACKREST_CIPHER_PASS
)

# 64 characters because AIRFLOW_JWT_SECRET is the HMAC key for HS512, which
# warns below 64 bytes per RFC 7518 section 3.2. One length for every value
# keeps the generator from having to reason about which is which.
SECRET_LENGTH=64

output_mode=print
output_path=""
project_id=""

while (( $# > 0 )); do
  case "$1" in
    --write)
      output_mode=write
      output_path="${2:?--write requires a path}"
      shift 2
      ;;
    --bws)
      output_mode=bws
      project_id="${2:?--bws requires a project ID}"
      shift 2
      ;;
    *)
      echo "unrecognized argument: $1" >&2
      exit 2
      ;;
  esac
done

# `head -c` closes the pipe and leaves `tr` killed by SIGPIPE, which pipefail
# would otherwise report as a failure.
alphanumeric_secret() {
  (
    set +o pipefail
    LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c "$SECRET_LENGTH"
  )
}

# A Fernet key is 32 random bytes in url-safe base64, which is what Airflow
# validates before it will decrypt any stored connection.
fernet_key() {
  head -c 32 /dev/urandom | base64 | tr '+/' '-_'
}

# Derived from the same arrays emit_secrets writes from, so a reported count
# cannot drift from the number of secrets actually produced. A literal here is
# a number that goes stale silently the next time a secret is added, which is
# exactly what happened when the pgBackRest cipher passphrase was introduced.
secret_count() {
  printf '%s' "$(( ${#SECRET_NAMES[@]} + 1 ))"
}

emit_secrets() {
  local secret_name
  for secret_name in "${SECRET_NAMES[@]}"; do
    printf '%s=%s\n' "$secret_name" "$(alphanumeric_secret)"
  done
  printf 'AIRFLOW_FERNET_KEY=%s\n' "$(fernet_key)"
}

# Reads the project back and checks the shape of what was actually stored. A
# value that arrives corrupted still creates a secret, so the runtime would only
# discover the problem when Airflow refused to decrypt a connection.
verify_stored_secrets() {
  echo "verifying stored secrets" >&2
  bws secret list "$project_id" -o json | python3 -c '
import base64, json, sys

expected = set(sys.argv[1:])
stored = {s["key"]: s["value"] for s in json.load(sys.stdin)}

problems = []
missing = expected - set(stored)
if missing:
    problems.append(f"missing: {sorted(missing)}")

for name, value in stored.items():
    if name not in expected:
        continue
    if name == "AIRFLOW_FERNET_KEY":
        try:
            decoded = base64.urlsafe_b64decode(value)
        except Exception as error:
            problems.append(f"{name}: not url-safe base64 ({error})")
            continue
        if len(decoded) != 32:
            problems.append(f"{name}: decodes to {len(decoded)} bytes, expected 32")
    elif not (value.isalnum() and value.isascii()):
        problems.append(f"{name}: must be alphanumeric to survive URL interpolation")
    elif len(value) < 32:
        problems.append(f"{name}: only {len(value)} characters")

if problems:
    print("stored secrets failed verification:", file=sys.stderr)
    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    sys.exit(1)
print(f"verified {len(expected)} secrets", file=sys.stderr)
' "${SECRET_NAMES[@]}" AIRFLOW_FERNET_KEY
}

case "$output_mode" in
  print)
    emit_secrets
    ;;
  write)
    if [[ -e "$output_path" ]]; then
      echo "refusing to replace an existing file: $output_path" >&2
      exit 2
    fi
    (
      umask 077
      emit_secrets >"$output_path"
    )
    chmod 0600 "$output_path"
    echo "wrote $(secret_count) secrets to $output_path with mode 0600" >&2
    echo "load them into Bitwarden, then remove the file" >&2
    ;;
  bws)
    for command_name in bws jq; do
      if ! command -v "$command_name" >/dev/null 2>&1; then
        echo "required command is unavailable: $command_name" >&2
        exit 2
      fi
    done
    if [[ -z "${BWS_ACCESS_TOKEN:-}" ]]; then
      echo "BWS_ACCESS_TOKEN is required and must have write access" >&2
      exit 2
    fi

    # Bitwarden throttles bursts of writes, and a duplicate key would leave the
    # project with two secrets of the same name for `bws run` to choose between.
    # Skipping names that already exist keeps a resumed or repeated run safe.
    existing_secret_names="$(bws secret list "$project_id" -o json | jq -r '.[].key')"

    created_count=0
    skipped_count=0
    # Split on the first `=` by substring rather than `IFS='=' read`: bash drops
    # a trailing IFS delimiter, which silently truncated the Fernet key's base64
    # padding and stored a value Airflow could not decode.
    while IFS= read -r secret_line; do
      secret_name="${secret_line%%=*}"
      secret_value="${secret_line#*=}"

      if grep -qxF "$secret_name" <<<"$existing_secret_names"; then
        echo "skipped $secret_name: already present in the project" >&2
        skipped_count=$((skipped_count + 1))
        continue
      fi

      attempt=1
      while true; do
        if creation_error="$(bws secret create --output none \
          "$secret_name" "$secret_value" "$project_id" 2>&1)"; then
          break
        fi
        if (( attempt >= 5 )); then
          echo "failed to create $secret_name after $attempt attempts:" >&2
          echo "$creation_error" >&2
          exit 1
        fi
        sleep "$attempt"
        attempt=$((attempt + 1))
      done
      echo "created $secret_name" >&2
      created_count=$((created_count + 1))
      sleep "${SECRET_CREATE_DELAY_SECONDS:-1}"
    done < <(emit_secrets)

    echo "created $created_count secret(s), skipped $skipped_count already present" >&2
    verify_stored_secrets
    ;;
esac
