#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
infra_dir="$(cd "$script_dir/.." && pwd)"
compose_environment_file="${COMPOSE_ENV_FILE:-$infra_dir/.env}"
bitwarden_environment_file="${BWS_ENV_FILE:-$infra_dir/.bws.env}"

for command_name in bws docker; do
  if ! command -v "$command_name" >/dev/null 2>&1; then
    echo "required command is unavailable: $command_name" >&2
    exit 2
  fi
done

for required_file in "$compose_environment_file" "$bitwarden_environment_file"; do
  if [[ ! -f "$required_file" ]]; then
    echo "required runtime configuration file is missing: $required_file" >&2
    exit 2
  fi
done

if [[ ! -O "$bitwarden_environment_file" ]]; then
  echo "Bitwarden configuration must be owned by the invoking user" >&2
  exit 2
fi

bitwarden_file_mode="$(stat -c '%a' "$bitwarden_environment_file")"
if (( (8#$bitwarden_file_mode & 077) != 0 )); then
  echo "Bitwarden configuration must not grant group or world permissions" >&2
  exit 2
fi

read_configuration_value() {
  local variable_name="$1"
  local configuration_file="$2"
  local matching_line
  matching_line="$(grep -m 1 -E "^${variable_name}=" "$configuration_file" || true)"
  printf '%s' "${matching_line#*=}"
}

BWS_ACCESS_TOKEN="$(read_configuration_value BWS_ACCESS_TOKEN "$bitwarden_environment_file")"
BWS_PROJECT_ID="$(read_configuration_value BWS_PROJECT_ID "$bitwarden_environment_file")"

if [[ -z "$BWS_ACCESS_TOKEN" || -z "$BWS_PROJECT_ID" ]]; then
  echo "Bitwarden access token and project ID are required" >&2
  exit 2
fi

export BWS_ACCESS_TOKEN
exec bws run \
  --project-id "$BWS_PROJECT_ID" \
  --no-inherit-env \
  -- docker compose \
  --env-file "$compose_environment_file" \
  --file "$infra_dir/compose.yaml" \
  "$@"
