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

AIRFLOW_UID="$(id -u)"

while IFS= read -r line || [[ -n "$line" ]]; do
  variable_name="${line%%=*}"
  case "$variable_name" in
    AIRFLOW_UID)
      printf '%s=%s\n' "$variable_name" "$AIRFLOW_UID" >>"$temporary_environment_file"
      ;;
    *)
      printf '%s\n' "$line" >>"$temporary_environment_file"
      ;;
  esac
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
