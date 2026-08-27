#!/usr/bin/env bash
# Restore the property-tax cluster to a point in time, into an isolated target.
#
# Re-execs itself under `bws run` when the cipher passphrase is absent, so the
# Bitwarden access token stays host-only and never reaches Compose or a
# container, and the passphrase reaches Docker by reference (`-e NAME`) rather
# than as `-e NAME=value`. A literal on the command line would land in shell
# history, in `ps` output, and in any process listing taken while the restore
# runs -- for the one value that makes every backup in S3 readable.
#
# The recovered cluster is started from the same pinned image with the same
# certificate mount, certificate group, and identity ARNs as production. That is
# not tidiness: reaching the requested timestamp requires PostgreSQL to run
# `archive-get` during startup, which needs working S3 credentials. A recovered
# container given only the restored volume can restore a base backup and then
# fail to replay to the target.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
infra_dir="$(cd "$script_dir/.." && pwd)"
compose_environment_file="${COMPOSE_ENV_FILE:-$infra_dir/.env}"
bitwarden_environment_file="${BWS_ENV_FILE:-$infra_dir/.bws.env}"

PRODUCTION_VOLUME="${PRODUCTION_VOLUME:-property-tax-platform_postgres-data}"
STANZA="${PGBACKREST_STANZA:-platform}"
RESTORE_PORT="${RESTORE_PORT:-55432}"
RESTORE_IMAGE="${RESTORE_IMAGE:-property-tax-postgres:${POSTGRES_VERSION:-16.11}}"

die() { printf 'pgbackrest-restore: %s\n' "$*" >&2; exit 2; }
info() { printf 'pgbackrest-restore: %s\n' "$*" >&2; }

usage() {
    cat >&2 <<'USAGE'
usage: pgbackrest-restore.sh --target "<timestamp>" [--volume NAME] [--port N] [--keep]

  --target   recovery target timestamp, e.g. "2026-08-27 01:23:45+00"
  --volume   temporary Docker volume to restore into (default: generated)
  --port     loopback port for the isolated cluster (default: 55432)
  --keep     leave the container and volume in place for inspection
USAGE
    exit 2
}

target=""
restore_volume=""
keep=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --target) target="${2:?--target needs a value}"; shift 2 ;;
        --volume) restore_volume="${2:?--volume needs a value}"; shift 2 ;;
        --port) RESTORE_PORT="${2:?--port needs a value}"; shift 2 ;;
        --keep) keep=true; shift ;;
        -h | --help) usage ;;
        *) die "unexpected argument: $1" ;;
    esac
done
[[ -n "$target" ]] || usage

# Re-exec under the Bitwarden boundary rather than asking the caller to remember
# to. The token is read here, on the host, and is not exported to the child.
if [[ -z "${PGBACKREST_CIPHER_PASS:-}" ]]; then
    [[ -f "$bitwarden_environment_file" ]] || die "missing $bitwarden_environment_file"
    [[ -O "$bitwarden_environment_file" ]] || die "Bitwarden configuration must be owned by the invoking user"
    mode="$(stat -c '%a' "$bitwarden_environment_file")"
    (( (8#$mode & 077) == 0 )) || die "Bitwarden configuration must not grant group or world permissions"

    token="$(grep -E '^BWS_ACCESS_TOKEN=' "$bitwarden_environment_file" | tail -n 1)"; token="${token#*=}"
    project="$(grep -E '^BWS_PROJECT_ID=' "$bitwarden_environment_file" | tail -n 1)"; project="${project#*=}"
    [[ -n "$token" && -n "$project" ]] || die "Bitwarden access token and project ID are required"

    # Fetch the one secret rather than re-exec under `bws run`.
    #
    # `bws run` does not preserve argument boundaries: it re-splits its child's
    # argv on whitespace, so `--target "2026-01-01 00:00:00+00"` arrives as two
    # arguments. Measured, not assumed. Re-execing through it would either fail
    # noisily on a good day or, if the parser were more forgiving, restore to a
    # different point in time than the operator asked for.
    #
    # The value transits a command substitution into this process's environment,
    # which is where it has to be anyway for `docker run -e NAME` to pass it by
    # reference. It never reaches argv, disk, or a container image.
    info "resolving the repository passphrase through Bitwarden"
    PGBACKREST_CIPHER_PASS="$(
        BWS_ACCESS_TOKEN="$token" bws run --project-id "$project" --no-inherit-env \
            -- printenv PGBACKREST_CIPHER_PASS
    )" || die "could not resolve PGBACKREST_CIPHER_PASS from the Bitwarden project"
    [[ -n "$PGBACKREST_CIPHER_PASS" ]] || die "PGBACKREST_CIPHER_PASS resolved empty"
    export PGBACKREST_CIPHER_PASS
fi

command -v docker >/dev/null 2>&1 || die "docker is unavailable"

read_configuration_value() {
    local line
    line="$(grep -E "^$1=" "$compose_environment_file" | tail -n 1 || true)"
    printf '%s' "${line#*=}"
}

certificate_directory="$(read_configuration_value TRUPRYCE_AWS_CERTIFICATE_DIR)"
certificate_directory="${certificate_directory:-/etc/trupryce/aws}"
certificate_gid="$(read_configuration_value TRUPRYCE_AWS_GID)"
certificate_gid="${certificate_gid:-2000}"
certificate="$(read_configuration_value PGBACKREST_AWS_CERTIFICATE)"
private_key="$(read_configuration_value PGBACKREST_AWS_PRIVATE_KEY)"
trust_anchor="$(read_configuration_value PGBACKREST_AWS_TRUST_ANCHOR_ARN)"
profile_arn="$(read_configuration_value PGBACKREST_AWS_PROFILE_ARN)"
role_arn="$(read_configuration_value PGBACKREST_AWS_ROLE_ARN)"

# Named by their configuration key, not by the shell variable holding them: an
# operator reading "does not define TRUST_ANCHOR" would grep the file for the
# wrong name and conclude the check was broken.
require_configured() {
    [[ -n "$2" ]] || die "$compose_environment_file does not define $1"
}
require_configured PGBACKREST_AWS_TRUST_ANCHOR_ARN "$trust_anchor"
require_configured PGBACKREST_AWS_PROFILE_ARN "$profile_arn"
require_configured PGBACKREST_AWS_ROLE_ARN "$role_arn"

if [[ -z "$restore_volume" ]]; then
    restore_volume="pitr-verify-$(date -u +%Y%m%d%H%M%S)-$$"
fi
container="pitr-verify-$$"

# The restore target must never be the production volume. Checked by name and
# again by the volume's own labels, because a caller could pass a differently
# named volume that Compose still owns.
[[ "$restore_volume" != "$PRODUCTION_VOLUME" ]] \
    || die "refusing to restore over the production volume $PRODUCTION_VOLUME"
if docker volume inspect "$restore_volume" >/dev/null 2>&1; then
    owner="$(docker volume inspect "$restore_volume" \
        --format '{{index .Labels "com.docker.compose.project"}}' 2>/dev/null || true)"
    [[ -z "$owner" || "$owner" == "<no value>" ]] \
        || die "refusing to restore into a Compose-managed volume owned by $owner"
fi

# Loopback only. A recovered cluster holds production data at an arbitrary past
# state and must not be reachable from the tailnet, let alone anywhere else.
bind_address="127.0.0.1"

cleanup() {
    if [[ "$keep" == true ]]; then
        info "--keep: leaving container $container and volume $restore_volume in place"
        return
    fi
    docker rm -f "$container" >/dev/null 2>&1 || true
    docker volume rm "$restore_volume" >/dev/null 2>&1 || true
    info "removed isolated container and volume"
}
trap cleanup EXIT

docker volume create "$restore_volume" >/dev/null
info "restoring into volume $restore_volume (target: $target)"

# -e NAME, never -e NAME=value: the passphrase passes by reference from this
# process's environment and never appears in argv.
export PGBACKREST_REPO1_CIPHER_PASS="$PGBACKREST_CIPHER_PASS"

identity_arguments=(
    -e PGBACKREST_REPO1_CIPHER_PASS
    -e "PGBACKREST_AWS_CERTIFICATE=$certificate"
    -e "PGBACKREST_AWS_PRIVATE_KEY=$private_key"
    -e "PGBACKREST_AWS_TRUST_ANCHOR_ARN=$trust_anchor"
    -e "PGBACKREST_AWS_PROFILE_ARN=$profile_arn"
    -e "PGBACKREST_AWS_ROLE_ARN=$role_arn"
    -v "$certificate_directory:/etc/trupryce/aws:ro"
    --group-add "$certificate_gid"
)

docker run --rm \
    -v "$restore_volume:/var/lib/postgresql/data" \
    "${identity_arguments[@]}" \
    --user postgres \
    "$RESTORE_IMAGE" \
    pgbackrest --stanza="$STANZA" --type=time --target="$target" \
        --target-action=promote --delta restore

info "restore complete; starting the isolated cluster on ${bind_address}:${RESTORE_PORT}"

# Same image, same certificate mount, same ARNs: recovery to the target runs
# archive-get, which needs credentials. Without them PostgreSQL starts from the
# base backup and stops short of the requested timestamp.
docker run -d --name "$container" \
    -p "${bind_address}:${RESTORE_PORT}:5432" \
    -v "$restore_volume:/var/lib/postgresql/data" \
    "${identity_arguments[@]}" \
    -e POSTGRES_HOST_AUTH_METHOD=trust \
    --memory 1g \
    "$RESTORE_IMAGE" >/dev/null

for _ in $(seq 1 60); do
    if docker exec "$container" pg_isready -U platform_admin >/dev/null 2>&1; then
        break
    fi
    sleep 2
done

docker exec "$container" pg_isready -U platform_admin >/dev/null 2>&1 \
    || { docker logs --tail 40 "$container" >&2; die "isolated cluster did not become ready"; }

printf '\n===== isolated recovery assertions =====\n'
docker exec "$container" psql -U platform_admin -d postgres -v ON_ERROR_STOP=1 -At <<'SQL'
SELECT 'property_tax database exists: ' ||
       (EXISTS (SELECT 1 FROM pg_database WHERE datname = 'property_tax'))::text;
SELECT 'airflow database exists:      ' ||
       (EXISTS (SELECT 1 FROM pg_database WHERE datname = 'airflow'))::text;
SELECT 'runtime roles present (4):    ' || count(*)::text
  FROM pg_roles
 WHERE rolname IN ('airflow_metadata','property_tax_migrator',
                   'property_tax_ingestion','property_tax_api');
SELECT 'in recovery (want false):     ' || pg_is_in_recovery()::text;
SQL

printf '\n===== marker table =====\n'
docker exec "$container" psql -U platform_admin -d postgres -At -c "
SELECT CASE WHEN to_regclass('public.recovery_marker') IS NULL
            THEN 'recovery_marker absent'
            ELSE 'markers: ' || (SELECT coalesce(string_agg(state, ',' ORDER BY state), '(none)')
                                 FROM public.recovery_marker) END;"

printf '\n===== isolation =====\n'
printf 'restored volume : %s\n' "$restore_volume"
printf 'production volume %s was not mounted: %s\n' "$PRODUCTION_VOLUME" \
    "$(docker inspect "$container" --format '{{range .Mounts}}{{.Name}} {{end}}' \
        | grep -qw "$PRODUCTION_VOLUME" && echo FALSE || echo true)"
printf 'published on    : %s\n' \
    "$(docker port "$container" 5432/tcp 2>/dev/null || echo 'not published')"
