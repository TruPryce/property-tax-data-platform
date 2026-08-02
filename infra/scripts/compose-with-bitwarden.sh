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

# Administrative ports must stay on loopback or the Tailscale CGNAT range
# (100.64.0.0/10). Docker publishes ports through its own iptables chain ahead of
# the host INPUT rules, so ufw will not contain a mistake here.
require_private_bind_address() {
  local variable_name="$1"
  local bind_address
  bind_address="$(read_configuration_value "$variable_name" "$compose_environment_file")"

  # Unset or empty falls through to the compose default of 127.0.0.1.
  [[ -z "$bind_address" ]] && return 0
  [[ "$bind_address" == localhost || "$bind_address" == "::1" ]] && return 0
  if [[ "$bind_address" =~ ^127\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    return 0
  fi
  if [[ "$bind_address" =~ ^100\.([0-9]+)\.[0-9]+\.[0-9]+$ ]]; then
    if (( BASH_REMATCH[1] >= 64 && BASH_REMATCH[1] <= 127 )); then
      return 0
    fi
  fi

  echo "$variable_name must bind to loopback or a Tailscale address, got: $bind_address" >&2
  echo "administrative ports must not be published on a public interface" >&2
  exit 2
}

require_private_bind_address POSTGRES_BIND_ADDRESS
require_private_bind_address AIRFLOW_API_BIND_ADDRESS

# `docker compose config` renders every resolved Bitwarden value to stdout.
# Refuse the forms that would print them rather than relying on the operator to
# remember --quiet.
if [[ "${1:-}" == "config" ]]; then
  config_output_is_bounded=false
  for argument in "$@"; do
    case "$argument" in
      --quiet | -q | --services | --volumes | --profiles | --images | --hash)
        config_output_is_bounded=true
        ;;
    esac
  done
  if [[ "$config_output_is_bounded" == false ]]; then
    echo "refusing to render the full compose configuration: it contains resolved secrets" >&2
    echo "use 'config --quiet' to validate, or '--services'/'--volumes' to inspect names" >&2
    exit 2
  fi
fi

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
