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

# Takes the last definition, because that is the one Compose resolves for a
# duplicated key. Reading the first would let a stale leading line mask the
# value actually in effect.
read_configuration_value() {
  local variable_name="$1"
  local configuration_file="$2"
  local matching_line
  matching_line="$(grep -E "^${variable_name}=" "$configuration_file" | tail -n 1 || true)"
  printf '%s' "${matching_line#*=}"
}

count_configuration_definitions() {
  local variable_name="$1"
  local configuration_file="$2"
  grep -c -E "^${variable_name}=" "$configuration_file" || true
}

# Administrative ports must stay on loopback or the Tailscale CGNAT range
# (100.64.0.0/10). Docker publishes ports through its own iptables chain ahead of
# the host INPUT rules, so ufw will not contain a mistake here.
require_private_bind_address() {
  local variable_name="$1"
  local bind_address definition_count
  bind_address="$(read_configuration_value "$variable_name" "$compose_environment_file")"

  # An ambiguous security control fails closed. Compose would silently take the
  # last definition while a reader checking the file could reasonably read the
  # first, so refuse rather than pick one.
  definition_count="$(count_configuration_definitions "$variable_name" "$compose_environment_file")"
  if (( definition_count > 1 )); then
    echo "$variable_name is defined $definition_count times in $compose_environment_file" >&2
    echo "remove the duplicates so the effective bind address is unambiguous" >&2
    exit 2
  fi

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

# `docker compose config` renders every resolved Bitwarden value to stdout, and
# `convert` is an alias for it. Compose accepts global options before the
# subcommand, so the subcommand is not necessarily the first argument: testing
# only "$1" lets `--profile debug config` walk straight past this guard.
compose_subcommand() {
  local -r value_options=" -f --file -p --project-name --profile --project-directory --env-file --parallel --progress --ansi --log-level "
  local expecting_value=false argument
  for argument in "$@"; do
    if [[ "$expecting_value" == true ]]; then
      expecting_value=false
      continue
    fi
    case "$argument" in
      --*=*) continue ;;
      -*)
        [[ "$value_options" == *" $argument "* ]] && expecting_value=true
        continue
        ;;
      *)
        printf '%s' "$argument"
        return 0
        ;;
    esac
  done
}

config_output_is_bounded=false
for argument in "$@"; do
  case "$argument" in
    --quiet | -q | --services | --volumes | --profiles | --images | --hash)
      config_output_is_bounded=true
      ;;
  esac
done

renders_full_configuration=false
case "$(compose_subcommand "$@")" in
  config | convert) renders_full_configuration=true ;;
esac
# Belt for an option this parser does not know about: if the rendering
# subcommand appears anywhere in the arguments, treat it as reachable.
for argument in "$@"; do
  case "$argument" in
    config | convert) renders_full_configuration=true ;;
  esac
done

if [[ "$renders_full_configuration" == true && "$config_output_is_bounded" == false ]]; then
  echo "refusing to render the full compose configuration: it contains resolved secrets" >&2
  echo "use 'config --quiet' to validate, or '--services'/'--volumes' to inspect names" >&2
  exit 2
fi

# A promotion-labelled volume that never finished verification must not become
# the next production primary.
#
# pgbackrest-restore.sh --promote labels the volume at creation, before any data
# exists, and writes the verified sentinel only after every assertion and a real
# write probe. An EXIT trap cleans up ordinary failures, but kill -9, a reboot,
# or power loss cannot run a trap -- so the label survives and the sentinel does
# not, and this refuses to start on it. A volume without the label, including
# every volume predating this mechanism, is untouched.
require_verified_promotion() {
    local project volume label sentinel
    project="$(read_configuration_value COMPOSE_PROJECT_NAME "$compose_environment_file")"
    project="${project:-property-tax-platform}"
    volume="${project}_postgres-data"

    docker volume inspect "$volume" >/dev/null 2>&1 || return 0

    label="$(docker volume inspect "$volume" \
        --format '{{index .Labels "trupryce.promotion"}}' 2>/dev/null || true)"
    [[ "$label" == "managed" ]] || return 0

    sentinel="$(docker run --rm -v "$volume:/v:ro" alpine:3.20 \
        sh -c 'cat /v/.trupryce-promotion 2>/dev/null || true' 2>/dev/null || true)"
    if [[ "$sentinel" == verified* ]]; then
        return 0
    fi

    echo "refusing to start: $volume was created by a promotion that did not complete" >&2
    echo "it carries the promotion label but no verified sentinel, so no restore of it" >&2
    echo "was ever proven. Remove it and re-run pgbackrest-restore.sh --promote:" >&2
    echo "  docker volume rm $volume" >&2
    exit 2
}

case "$(compose_subcommand "$@")" in
    up | start | run | create) require_verified_promotion ;;
esac

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
