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

PROMOTION_LABEL="trupryce.promotion"
PROMOTION_NONCE_LABEL="trupryce.promotion.nonce"
# Verification state lives in a sidecar Docker volume, never inside PGDATA.
# A file written into the data directory is captured by the next backup --
# measured: a probe file appeared in the diff manifest as
# pg_data/.trupryce-promotion-probe.zst -- so restoring that backup would
# carry an old "verified" marker into a NEW, unverified promotion and defeat
# the gate. The nonce binds the proof to one promotion, so a sidecar left
# over from an earlier one does not authorise a later one either.
PROMOTION_VERIFIED_SUFFIX=".verified"
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-property-tax-platform}"
COMPOSE_VOLUME_NAME="${COMPOSE_VOLUME_NAME:-postgres-data}"
PRODUCTION_VOLUME="${PRODUCTION_VOLUME:-${COMPOSE_PROJECT_NAME}_${COMPOSE_VOLUME_NAME}}"
STANZA="${PGBACKREST_STANZA:-platform}"
RESTORE_PORT="${RESTORE_PORT:-55432}"
RESTORE_IMAGE="${RESTORE_IMAGE:-property-tax-postgres:${POSTGRES_VERSION:-16.11}}"

die() { printf 'pgbackrest-restore: %s\n' "$*" >&2; exit 2; }
info() { printf 'pgbackrest-restore: %s\n' "$*" >&2; }

# Validate a restored migration ledger against this checkout.
#
# Reads "<version> <sha256>" lines on stdin and echoes a verdict beginning
# "true" or "false". "Non-empty" is not a check: the ledger is the authority for
# what was applied and carries file_sha256 precisely so the answer can be
# verified. A gap means a migration is missing from the restored cluster; a hash
# mismatch means the SQL that ran is not the SQL in the repository.
#
# A function so it can be exercised directly, which is how the contiguity and
# mismatch paths are tested without applying migrations anywhere.
validate_migration_ledger() {
    local migrations_dir="$1"
    local row version hash expected=1 candidate file_hash
    local saw_row=false

    while IFS= read -r row; do
        [[ -n "$(printf '%s' "$row" | tr -d '[:space:]')" ]] || continue
        saw_row=true
        row="${row#"${row%%[![:space:]]*}"}"
        version="${row%% *}"
        hash="${row##* }"

        if (( 10#$version != expected )); then
            printf 'false (version %s breaks contiguity, expected %s)\n' "$version" "$expected"
            return 0
        fi

        candidate="$(printf '%s/%04d_' "$migrations_dir" "$((10#$version))")"*.sql
        # shellcheck disable=SC2086
        set -- $candidate
        if [[ ! -r "$1" ]]; then
            printf 'false (no migration file for version %s in this checkout)\n' "$version"
            return 0
        fi

        file_hash="$(sha256sum "$1" | cut -d' ' -f1)"
        if [[ "$file_hash" != "$hash" ]]; then
            printf 'false (version %s hash differs from %s)\n' "$version" "$(basename "$1")"
            return 0
        fi
        expected=$((expected + 1))
    done

    if [[ "$saw_row" != true ]]; then
        printf 'false (ledger present but empty)\n'
        return 0
    fi
    printf 'true (%s contiguous, hashes match this checkout)\n' "$((expected - 1))"
}

usage() {
    cat >&2 <<'USAGE'
usage: pgbackrest-restore.sh --target "<timestamp>" [--volume NAME] [--port N] [--keep]
       pgbackrest-restore.sh --promote [--target "<timestamp>"] [--port N]

  --target   recovery target timestamp, e.g. "2026-08-27 01:23:45+00"
  --volume   temporary Docker volume to restore into (default: generated)
  --port     loopback port for the isolated cluster (default: 55432)
  --keep     leave the container and volume in place for inspection
  --exercise periodic PITR drill (default). Restores into a throwaway volume and
             additionally requires the disposable before/after markers, which is
             what proves the recovery TARGET was honoured rather than that a
             restore merely happened.
  --promote  clean-host mode: restore into the PRODUCTION volume, verify it in
             isolation, and leave it for Compose to adopt. Requires that the
             production volume does not yet exist, so it can never overwrite a
             live cluster. Does NOT require the drill markers -- a real
             migration or disaster restores a cluster that has no such table.
USAGE
    exit 2
}

target=""
restore_volume=""
keep=false
promote=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --target) target="${2:?--target needs a value}"; shift 2 ;;
        --volume) restore_volume="${2:?--volume needs a value}"; shift 2 ;;
        --port) RESTORE_PORT="${2:?--port needs a value}"; shift 2 ;;
        --keep) keep=true; shift ;;
        --exercise) promote=false; shift ;;
        --promote) promote=true; shift ;;
        -h | --help) usage ;;
        *) die "unexpected argument: $1" ;;
    esac
done
# A drill must name a target: the whole point is proving a chosen point in time
# was honoured. A promotion defaults to the end of the archive, because a
# migration or disaster wants everything that was successfully archived, not a
# historical moment -- and because a timestamp later than the last commit makes
# PostgreSQL fail with "recovery ended before configured recovery target was
# reached", which on an idle database is any timestamp at all.
if [[ "$promote" != true && -z "$target" ]]; then
    die "--target is required for a PITR exercise; --promote may omit it to restore to the end of the archive"
fi
[[ "$promote" == true && -n "$restore_volume" ]] \
    && die "--promote restores into $PRODUCTION_VOLUME; --volume cannot be combined with it"

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
certificate="$(read_configuration_value TRUPRYCE_AWS_CERTIFICATE)"
private_key="$(read_configuration_value TRUPRYCE_AWS_PRIVATE_KEY)"
trust_anchor="$(read_configuration_value TRUPRYCE_AWS_TRUST_ANCHOR_ARN)"
profile_arn="$(read_configuration_value TRUPRYCE_AWS_PROFILE_ARN)"
role_arn="$(read_configuration_value TRUPRYCE_AWS_ROLE_ARN)"

# Named by their configuration key, not by the shell variable holding them: an
# operator reading "does not define TRUST_ANCHOR" would grep the file for the
# wrong name and conclude the check was broken.
require_configured() {
    [[ -n "$2" ]] || die "$compose_environment_file does not define $1"
}
require_configured TRUPRYCE_AWS_TRUST_ANCHOR_ARN "$trust_anchor"
require_configured TRUPRYCE_AWS_PROFILE_ARN "$profile_arn"
require_configured TRUPRYCE_AWS_ROLE_ARN "$role_arn"

if [[ -z "$restore_volume" ]]; then
    restore_volume="pitr-verify-$(date -u +%Y%m%d%H%M%S)-$$"
fi
container="pitr-verify-$$"

if [[ "$promote" == true ]]; then
    # Clean-host promotion. The verification runs against the volume Compose
    # will actually adopt, rather than against a copy of it -- verifying one
    # volume and starting another is how a restore gets declared good and then
    # is not the thing that runs.
    #
    # Safe because the production volume must NOT already exist. That single
    # precondition is what separates "rebuild a dead host" from "overwrite a
    # live cluster", and it is checked rather than trusted to the operator.
    restore_volume="$PRODUCTION_VOLUME"
    if docker volume inspect "$restore_volume" >/dev/null 2>&1; then
        die "$PRODUCTION_VOLUME already exists; --promote is for a host that has none.
    To rebuild deliberately, stop the stack and remove the volume first, which is
    a decision that should be explicit rather than a side effect of a restore."
    fi
    if [[ -n "$(docker ps -aq --filter "volume=$PRODUCTION_VOLUME")" ]]; then
        die "containers are still attached to $PRODUCTION_VOLUME"
    fi
else
    # The restore target must never be the production volume. Checked by name and
    # again by the volume's own labels, because a caller could pass a differently
    # named volume that Compose still owns.
    [[ "$restore_volume" != "$PRODUCTION_VOLUME" ]] \
        || die "refusing to restore over the production volume $PRODUCTION_VOLUME (use --promote on a clean host)"
    if docker volume inspect "$restore_volume" >/dev/null 2>&1; then
        owner="$(docker volume inspect "$restore_volume" \
            --format '{{index .Labels "com.docker.compose.project"}}' 2>/dev/null || true)"
        [[ -z "$owner" || "$owner" == "<no value>" ]] \
            || die "refusing to restore into a Compose-managed volume owned by $owner"
    fi
fi

# Loopback only. A recovered cluster holds production data at an arbitrary past
# state and must not be reachable from the tailnet, let alone anywhere else.
bind_address="127.0.0.1"

verified=false
cleanup() {
    if [[ "$promote" == true ]]; then
        # The container always goes; the volume's fate depends on whether the
        # assertions passed. Keeping an unverified volume would leave Compose
        # ready to adopt a restore nobody proved.
        docker rm -f "$container" >/dev/null 2>&1 || true
        if [[ "$verified" == true ]]; then
            # Recorded only here, after every assertion and the write probe, and
            # as Docker metadata rather than a file in PGDATA so no backup can
            # capture it and no restore can replay it.
            docker volume create \
                --label "$PROMOTION_NONCE_LABEL=$promotion_nonce" \
                --label "$PROMOTION_LABEL=verified" \
                "${restore_volume}${PROMOTION_VERIFIED_SUFFIX}" >/dev/null \
                || die "could not record verification for $restore_volume"
            info "verified; $restore_volume is ready for Compose to adopt"
            info "next: ./infra/scripts/compose-with-bitwarden.sh up -d"
        else
            docker volume rm "$restore_volume" >/dev/null 2>&1 || true
            docker volume rm "${restore_volume}${PROMOTION_VERIFIED_SUFFIX}" >/dev/null 2>&1 || true
            info "verification did not pass; removed $restore_volume so it cannot be adopted"
        fi
        return
    fi
    if [[ "$keep" == true ]]; then
        info "--keep: leaving container $container and volume $restore_volume in place"
        return
    fi
    docker rm -f "$container" >/dev/null 2>&1 || true
    docker volume rm "$restore_volume" >/dev/null 2>&1 || true
    info "removed isolated container and volume"
}
trap cleanup EXIT

if [[ "$promote" == true ]]; then
    # Labelled as Compose labels its own, so `docker volume ls` and Compose
    # tooling see it the same way after adoption.
    # The promotion label is written by Docker when the volume is created,
    # before any data exists, and cannot be lost by a crash the way an EXIT trap
    # can. Together with the sentinel written only after verification, it means
    # a volume interrupted at ANY point -- kill -9, reboot, power loss -- is
    # still recognisably unverified, because the label says it was promoted and
    # no sentinel says it passed. A volume without the label, such as one that
    # predates this mechanism, is unaffected.
    promotion_nonce="$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    docker volume create \
        --label com.docker.compose.project="$COMPOSE_PROJECT_NAME" \
        --label com.docker.compose.volume="$COMPOSE_VOLUME_NAME" \
        --label "$PROMOTION_LABEL=managed" \
        --label "$PROMOTION_NONCE_LABEL=$promotion_nonce" \
        "$restore_volume" >/dev/null
    # A sidecar from a previous promotion must never vouch for this one.
    docker volume rm "${restore_volume}${PROMOTION_VERIFIED_SUFFIX}" >/dev/null 2>&1 || true
else
    docker volume create "$restore_volume" >/dev/null
fi

# -e NAME, never -e NAME=value: the passphrase passes by reference from this
# process's environment and never appears in argv.
export PGBACKREST_REPO1_CIPHER_PASS="$PGBACKREST_CIPHER_PASS"

identity_arguments=(
    -e PGBACKREST_REPO1_CIPHER_PASS
    -e "TRUPRYCE_AWS_CERTIFICATE=$certificate"
    -e "TRUPRYCE_AWS_PRIVATE_KEY=$private_key"
    -e "TRUPRYCE_AWS_TRUST_ANCHOR_ARN=$trust_anchor"
    -e "TRUPRYCE_AWS_PROFILE_ARN=$profile_arn"
    -e "TRUPRYCE_AWS_ROLE_ARN=$role_arn"
    -v "$certificate_directory:/etc/trupryce/aws:ro"
    --group-add "$certificate_gid"
)

# --target-action is only valid alongside --type. With no target, PostgreSQL
# replays to the end of the archive and promotes on its own, because pgBackRest
# writes recovery.signal rather than standby.signal.
restore_arguments=(--stanza="$STANZA" --delta restore)
if [[ -n "$target" ]]; then
    restore_arguments=(--stanza="$STANZA" --type=time --target="$target"
                       --target-action=promote --delta restore)
    info "restoring into volume $restore_volume (target: $target)"
else
    info "restoring into volume $restore_volume (target: end of archive)"
fi

docker run --rm --init \
    -v "$restore_volume:/var/lib/postgresql/data" \
    "${identity_arguments[@]}" \
    --user postgres \
    "$RESTORE_IMAGE" \
    pgbackrest "${restore_arguments[@]}"

info "restore complete; starting the isolated cluster on ${bind_address}:${RESTORE_PORT}"

# Same image, same certificate mount, same ARNs: recovery to the target runs
# archive-get, which needs credentials. Without them PostgreSQL starts from the
# base backup and stops short of the requested timestamp.
# Overwrite the Compose labels inherited from the image so this container can
# never be mistaken for the production service by a label selector -- including
# the backup timers', which would otherwise see two candidates.
# --init for the same reason production sets `init: true`: recovery runs
# archive-get, whose daemonized worker would otherwise be orphaned onto a
# PostgreSQL running as PID 1.
docker run -d --init --name "$container" \
    --label com.docker.compose.project=pitr-verify \
    --label com.docker.compose.service=pitr-verify \
    --label com.docker.compose.oneoff=True \
    -p "${bind_address}:${RESTORE_PORT}:5432" \
    -v "$restore_volume:/var/lib/postgresql/data" \
    "${identity_arguments[@]}" \
    -e POSTGRES_HOST_AUTH_METHOD=trust \
    --memory 1g \
    "$RESTORE_IMAGE" >/dev/null

# Readiness is not promotion. `pg_isready` reports OK while the cluster is
# still replaying WAL toward the target, so a check made at that moment finds
# pg_is_in_recovery() true and looks like a failed recovery. Wait for the
# promotion --target-action=promote performs once the target is reached.
promoted=false
for _ in $(seq 1 90); do
    if docker exec "$container" pg_isready -U platform_admin >/dev/null 2>&1; then
        in_recovery="$(docker exec "$container" psql -U platform_admin -d postgres -tAc \
            'SELECT pg_is_in_recovery()' 2>/dev/null | tr -d '[:space:]')"
        if [[ "$in_recovery" == "f" ]]; then
            promoted=true
            break
        fi
    fi
    sleep 2
done

if [[ "$promoted" != true ]]; then
    docker logs --tail 40 "$container" >&2
    die "isolated cluster did not finish recovery and promote within the timeout"
fi

# -c rather than a heredoc: `docker exec` without -i has no stdin, so a
# heredoc reaches psql as an empty script and every assertion silently prints
# nothing -- an exercise that looks like it ran and asserted zero things.
printf '\n===== isolated recovery assertions =====\n'
# Two contracts, because a drill and a disaster restore are not the same thing.
#
# The drill additionally requires the disposable before/after markers, which is
# the only assertion that proves the recovery TARGET was honoured rather than
# that a restore merely happened -- so it must not be weakened.
#
# A promotion must not require them. The markers are a testing artifact the
# runbook drops from production afterwards, so a real migration or disaster
# restores a cluster that has no such table. Requiring it there would fail every
# genuine recovery and, worse, destroy the restored volume on the way out.
common_assertions="
SELECT '  1. property_tax database exists : ' || (EXISTS (SELECT 1 FROM pg_database WHERE datname='property_tax'))::text
UNION ALL SELECT '  2. airflow database exists      : ' || (EXISTS (SELECT 1 FROM pg_database WHERE datname='airflow'))::text
UNION ALL SELECT '  3. runtime roles present (want 4): ' || (SELECT count(*) FROM pg_roles WHERE rolname IN ('airflow_metadata','property_tax_migrator','property_tax_ingestion','property_tax_api'))::text
UNION ALL SELECT '  4. pg_is_in_recovery() is false : ' || (NOT pg_is_in_recovery())::text"

if [[ "$promote" == true ]]; then
    # 5 proves this is a writable primary rather than a cluster that merely
    # finished replay. 6 reports the migration ledger without requiring it:
    # absent is correct before task 3.4 is applied, and a present-but-empty
    # ledger would mean the restore lost it.
    if [[ "$(docker exec "$container" psql -U platform_admin -d property_tax -tAc \
             "SELECT to_regclass('platform.schema_migration') IS NOT NULL" 2>/dev/null \
             | tr -d '[:space:]')" == "t" ]]; then
        ledger="$(docker exec "$container" psql -U platform_admin -d property_tax -tAc \
            "SELECT version || ' ' || file_sha256 FROM platform.schema_migration ORDER BY version" \
            2>/dev/null | validate_migration_ledger "$(cd "$infra_dir/.." && pwd)/infra/postgres/migrations")"
    else
        ledger="true (absent; pre-migration cluster)"
    fi
    assertion_query="$common_assertions
UNION ALL SELECT '  5. accepts writes (real primary) : ' || (SELECT CASE WHEN pg_is_in_recovery() THEN 'false' ELSE 'true' END)
UNION ALL SELECT '  6. migration ledger consistent   : ' || \$\$${ledger}\$\$"
else
    assertion_query="$common_assertions
UNION ALL SELECT '  5. marker before present        : ' || (EXISTS (SELECT 1 FROM public.recovery_marker WHERE state='before'))::text
UNION ALL SELECT '  6. marker after ABSENT          : ' || (NOT EXISTS (SELECT 1 FROM public.recovery_marker WHERE state='after'))::text"
fi

assertions=$(docker exec "$container" psql -U platform_admin -d postgres -v ON_ERROR_STOP=1 -tAc "$assertion_query")
printf '%s\n' "$assertions"

# An empty or short result means the assertions did not run. Fail loudly rather
# than reporting a successful exercise that proved nothing.
if [[ "$(printf '%s\n' "$assertions" | grep -c .)" -ne 6 ]]; then
    die "recovery assertions did not execute; refusing to report a passing exercise"
fi
if printf '%s' "$assertions" | grep -qE ': false$|: false |\(want 4\): [0-3]$'; then
    die "a recovery assertion failed"
fi

if [[ "$promote" == true ]]; then
    # Assertion 5 says the cluster is out of recovery; this proves it by doing
    # it, because "not in recovery" and "accepts a write" have differed before.
    docker exec "$container" psql -U platform_admin -d postgres -v ON_ERROR_STOP=1 -qc \
        'CREATE TABLE IF NOT EXISTS public.trupryce_promotion_probe (checked_at timestamptz primary key);
         INSERT INTO public.trupryce_promotion_probe VALUES (now());
         DROP TABLE public.trupryce_promotion_probe;' >/dev/null \
        || die "restored cluster did not accept a write; not promoting it"
    info "write probe succeeded"
fi
verified=true

printf '\n===== isolation =====\n'
printf 'restored volume : %s\n' "$restore_volume"
if [[ "$promote" == true ]]; then
    # In promote mode the production volume is deliberately the target, so the
    # "was not mounted" assertion would be both false and meaningless. What
    # matters here is that it did not exist beforehand, checked before any
    # restore began, and that verification ran against the very volume Compose
    # will adopt rather than a copy of it.
    printf 'mode            : promote (verified in isolation, then left for Compose)\n'
    printf 'precondition    : %s did not exist before this run\n' "$PRODUCTION_VOLUME"
else
    printf 'production volume %s was not mounted: %s\n' "$PRODUCTION_VOLUME" \
        "$(docker inspect "$container" --format '{{range .Mounts}}{{.Name}} {{end}}' \
            | grep -qw "$PRODUCTION_VOLUME" && echo FALSE || echo true)"
fi
printf 'published on    : %s\n' \
    "$(docker port "$container" 5432/tcp 2>/dev/null || echo 'not published')"
