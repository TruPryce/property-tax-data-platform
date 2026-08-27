#!/usr/bin/env bash
set -Eeuo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
infra_dir="$(cd "$script_dir/.." && pwd)"
template_file="$infra_dir/.env.example"
environment_file="${1:-$infra_dir/.env}"
bitwarden_template_file="$infra_dir/.bws.env.example"
bitwarden_environment_file="${2:-$infra_dir/.bws.env}"

if [[ -e "$environment_file" || -e "$bitwarden_environment_file" ]]; then
  echo "refusing to replace an existing runtime configuration file" >&2
  exit 2
fi

if [[ -z "${BWS_ACCESS_TOKEN:-}" ]]; then
  echo "BWS_ACCESS_TOKEN is required" >&2
  exit 2
fi

if [[ -z "${BWS_PROJECT_ID:-}" ]]; then
  echo "BWS_PROJECT_ID is required" >&2
  exit 2
fi

umask 077
temporary_environment_file="$(mktemp "${environment_file}.tmp.XXXXXX")"
temporary_bitwarden_file="$(mktemp "${bitwarden_environment_file}.tmp.XXXXXX")"
trap 'rm -f "$temporary_environment_file" "$temporary_bitwarden_file"' EXIT

# AIRFLOW_UID stays at the image's own 50000 rather than tracking the invoking
# user. Nothing here needs a host-matched UID: dags are mounted read-only and
# logs live in a named volume. Deriving it from `id -u` would silently run every
# Airflow service as root whenever the bootstrap is invoked under sudo.
while IFS= read -r line || [[ -n "$line" ]]; do
  printf '%s\n' "$line" >>"$temporary_environment_file"
done <"$template_file"

while IFS= read -r line || [[ -n "$line" ]]; do
  variable_name="${line%%=*}"
  case "$variable_name" in
    BWS_ACCESS_TOKEN | BWS_PROJECT_ID)
      printf '%s=%s\n' "$variable_name" "${!variable_name}" >>"$temporary_bitwarden_file"
      ;;
    *)
      printf '%s\n' "$line" >>"$temporary_bitwarden_file"
      ;;
  esac
done <"$bitwarden_template_file"

chmod 0600 "$temporary_environment_file" "$temporary_bitwarden_file"
mv "$temporary_environment_file" "$environment_file"
mv "$temporary_bitwarden_file" "$bitwarden_environment_file"
trap - EXIT
echo "created $environment_file and $bitwarden_environment_file with mode 0600"

# The template is a template. It carries one deliberately blank value and a set
# of certificate paths named for the host it was first written on, so copying it
# verbatim onto a replacement host produces a file that looks complete and is
# not. Say so here rather than letting it surface later as a credential error
# during the first archive attempt.
needs_attention=()
while IFS= read -r line; do
  [[ "$line" == TRUPRYCE_AWS_* ]] || continue
  name="${line%%=*}"
  value="${line#*=}"
  if [[ -z "$value" ]]; then
    needs_attention+=("$name (empty)")
  elif [[ "$value" == *trupryce-data-platform-vps* ]]; then
    needs_attention+=("$name (names the Akamai host identity)")
  fi
done <"$environment_file"

if (( ${#needs_attention[@]} > 0 )); then
  {
    echo
    echo "before this host can archive, set these in $environment_file:"
    printf '  - %s\n' "${needs_attention[@]}"
    echo
    echo "then run, as root:"
    echo "  ./infra/scripts/install-signing-helper.sh"
    echo "  ./infra/scripts/install-certificate-identity.sh"
    echo
    echo "install-certificate-identity.sh refuses to run while any of them is unset,"
    echo "so it is the gate rather than this warning."
  } >&2
fi
