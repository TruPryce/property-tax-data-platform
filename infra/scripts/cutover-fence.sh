#!/usr/bin/env bash
# Fence every writer, flush the final WAL, and report the recoverable boundary.
#
# For a PLANNED provider move. A restore reproduces the archive, not the source:
# anything committed on the old host after the last archived WAL simply is not
# in the new primary, and nothing about the restore will say so. Airflow's
# metadata alone makes that real even when ingestion is idle -- scheduler
# heartbeats, task instance states, and XComs are writes.
#
# So the order matters and it is the opposite of intuition: fence FIRST, then
# take the boundary. Restoring first and fencing afterwards leaves a window
# whose size is however long verification took.
#
# This does not cut over. It stops writers, proves the database is quiescent,
# forces the final segment into S3, and prints the point the new host should
# restore to. Cutover stays a human decision.
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
infra_dir="$(cd "$script_dir/.." && pwd)"
export PATH="$HOME/.local/bin:$PATH"

STANZA="${PGBACKREST_STANZA:-platform}"
BUCKET="${PGBACKREST_BUCKET:-trupryce-property-tax-backups}"
REPO_PATH="${PGBACKREST_REPO_PATH:-pgbackrest/platform}"
AWS_PROFILE_NAME="${AWS_PROFILE_NAME:-trupryce-backup}"
COMPOSE_PROJECT="${COMPOSE_PROJECT:-property-tax-platform}"

die() { printf 'cutover-fence: %s\n' "$*" >&2; exit 2; }
info() { printf 'cutover-fence: %s\n' "$*" >&2; }

command -v docker >/dev/null 2>&1 || die "docker is unavailable"
command -v aws >/dev/null 2>&1 || die "aws CLI is unavailable (install-signing-helper.sh and the AWS CLI are prerequisites)"

postgres_container() {
    docker ps --quiet \
        --filter "label=com.docker.compose.project=${COMPOSE_PROJECT}" \
        --filter "label=com.docker.compose.service=postgres" \
        --filter "label=com.docker.compose.oneoff=False"
}

container="$(postgres_container)"
[[ -n "$container" ]] || die "no running PostgreSQL container for project $COMPOSE_PROJECT"
[[ "$(printf '%s\n' "$container" | wc -l)" -eq 1 ]] || die "more than one PostgreSQL container matched"

# The runtime roles the bootstrap creates. platform_admin is deliberately absent:
# the operator still needs a way in, and it is not an application writer.
RUNTIME_ROLES=(airflow_metadata property_tax_migrator property_tax_ingestion property_tax_api)

psql_query() {
    docker exec "$container" psql -U platform_admin -d postgres -tAc "$1"
}

# Destination activation, and the reason it is not merely the inverse of the fence.
#
# NOLOGIN is a role attribute, so it is part of the physical state the fence
# leaves behind -- and therefore part of what a restore reproduces. A Hostinger
# promotion restores a *fenced* cluster: verification passes, the database is
# writable as platform_admin, and then Airflow cannot authenticate because
# airflow_metadata still cannot log in.
#
# So activation is a required step after promotion, not an undo. It runs
# unconditionally: on a disaster restore whose roles were never fenced,
# ALTER ROLE ... LOGIN is a no-op and the procedure stays the same either way.
#
# It also archives the transition. Leaving the LOGIN change unarchived means the
# next restore of this cluster is fenced again for no visible reason.
unfence() {
    printf '\n===== 1. restore login authority =====\n'
    for role in "${RUNTIME_ROLES[@]}"; do
        psql_query "ALTER ROLE $role LOGIN" >/dev/null
        printf '  %s: LOGIN\n' "$role"
    done

    printf '\n===== 2. prove each role can authenticate =====\n'
    local activated=true
    for role in "${RUNTIME_ROLES[@]}"; do
        if docker exec "$container" psql -U "$role" -d postgres -tAc 'SELECT 1' >/dev/null 2>&1; then
            printf '  %s: authenticated\n' "$role"
        else
            printf '  %s: STILL CANNOT AUTHENTICATE\n' "$role"
            activated=false
        fi
    done
    $activated || die "activation incomplete; do not start the runtime while a role cannot log in"

    printf '\n===== 3. archive the activation =====\n'
    local segment deadline archived=false archive_mode
    # Start PostgreSQL through Compose, which sets archive_mode=on. A cluster
    # started by hand without it cannot archive anything, and this step would
    # otherwise sit for five minutes before reporting a timeout that says
    # nothing about the actual cause.
    archive_mode="$(psql_query "SHOW archive_mode" | tr -d '[:space:]')"
    if [[ "$archive_mode" != "on" ]]; then
        die "archive_mode is '$archive_mode'; start PostgreSQL with
    ./infra/scripts/compose-with-bitwarden.sh up -d postgres
  so the activation can be archived, then run --unfence again."
    fi
    segment="$(psql_query "SELECT pg_walfile_name(pg_switch_wal())" | tr -d '[:space:]')"
    printf '  switched: %s\n' "$segment"
    deadline=$((SECONDS + 300))
    while (( SECONDS < deadline )); do
        if aws --profile "$AWS_PROFILE_NAME" s3 ls --recursive \
            "s3://${BUCKET}/${REPO_PATH}/archive/${STANZA}/" 2>/dev/null | grep -q "$segment"; then
            archived=true
            break
        fi
        sleep 3
    done
    if $archived; then
        printf '  confirmed in S3: %s\n' "$segment"
    else
        die "the activation was not archived within 300s; a later restore of this cluster would come back fenced"
    fi

    printf '\n'
    info "activated; all four runtime roles can authenticate and the transition is archived"
    info "now start the rest of the runtime: ./infra/scripts/compose-with-bitwarden.sh up -d"
    exit 0
}

[[ "${1:-}" == "--unfence" ]] && unfence

printf '\n===== 1. stop known writers =====\n'
# Airflow is the writer that never stops on its own: the scheduler heartbeats
# into its metadata database every few seconds whether or not any DAG runs.
for service in airflow-scheduler airflow-triggerer airflow-dag-processor airflow-api-server; do
    running="$(docker ps --quiet \
        --filter "label=com.docker.compose.project=${COMPOSE_PROJECT}" \
        --filter "label=com.docker.compose.service=${service}")"
    if [[ -n "$running" ]]; then
        docker stop "$running" >/dev/null
        printf '  stopped %s\n' "$service"
    else
        printf '  %s already stopped\n' "$service"
    fi
done

printf '\n===== 2. revoke login authority =====\n'
# Stopping containers is not a fence. Anything that can still authenticate can
# reconnect the moment after a zero-client check passes -- a restart policy, an
# operator, a forgotten cron, a second host still pointed here -- and the writes
# it makes land after the boundary and are lost silently.
#
# NOLOGIN is the enforcement: it denies authentication outright, so it does not
# depend on database ownership the way REVOKE CONNECT does, and it is reversed
# by --unfence.
for role in "${RUNTIME_ROLES[@]}"; do
    psql_query "ALTER ROLE $role NOLOGIN" >/dev/null
    printf '  %s: NOLOGIN\n' "$role"
done

printf '\n===== 3. terminate existing sessions =====\n'
# count(pg_terminate_backend(pid)) over pg_stat_activity. The form
# `FROM pg_terminate_backend(pid) WHERE pid IN (...)` is invalid -- there is no
# `pid` column in scope there -- and fails with `column "pid" does not exist`,
# which on a fence means step 3 errors out having terminated nothing.
terminated="$(psql_query "
SELECT count(pg_terminate_backend(pid))
FROM pg_stat_activity
WHERE pid <> pg_backend_pid()
  AND backend_type = 'client backend'
  AND usename = ANY(ARRAY['airflow_metadata','property_tax_migrator','property_tax_ingestion','property_tax_api'])" \
  | tr -d '[:space:]')"
printf '  terminated %s session(s)\n' "${terminated:-0}"

printf '\n===== 4. prove a fresh login now fails =====\n'
# The check that matters. A zero-client count only says nobody happens to be
# connected; this says nobody can connect.
fence_holds=true
for role in "${RUNTIME_ROLES[@]}"; do
    if docker exec "$container" psql -U "$role" -d postgres -tAc 'SELECT 1' >/dev/null 2>&1; then
        printf '  %s: STILL ABLE TO LOG IN\n' "$role"
        fence_holds=false
    else
        printf '  %s: login refused\n' "$role"
    fi
done
$fence_holds || die "the fence does not hold; do NOT take a boundary while a runtime role can connect"

remaining="$(psql_query "
SELECT coalesce(string_agg(DISTINCT usename || '@' || coalesce(client_addr::text,'local') || ' (' || datname || ')', ', '), '')
FROM pg_stat_activity
WHERE pid <> pg_backend_pid()
  AND backend_type = 'client backend'
  AND usename IS NOT NULL
  AND usename <> 'platform_admin'")"
if [[ -n "$remaining" ]]; then
    printf '  still connected: %s\n' "$remaining"
    die "clients remain connected after fencing; investigate before taking the boundary"
fi
printf '  no non-administrative client backends remain\n'

printf '\n===== 5. flush the final WAL segment =====\n'
final_segment="$(psql_query "SELECT pg_walfile_name(pg_switch_wal())" | tr -d '[:space:]')"
printf '  switched: %s\n' "$final_segment"

printf '\n===== 6. wait for it to reach S3 =====\n'
deadline=$((SECONDS + 300))
archived=false
while (( SECONDS < deadline )); do
    if aws --profile "$AWS_PROFILE_NAME" s3 ls --recursive \
        "s3://${BUCKET}/${REPO_PATH}/archive/${STANZA}/" 2>/dev/null | grep -q "$final_segment"; then
        archived=true
        break
    fi
    sleep 3
done
$archived || die "final segment $final_segment did not reach S3 within 300s; do NOT cut over"
printf '  confirmed in S3: %s\n' "$final_segment"

failed="$(psql_query "SELECT failed_count FROM pg_stat_archiver" | tr -d '[:space:]')"
last_archived="$(psql_query "SELECT coalesce(last_archived_wal,'none') FROM pg_stat_archiver" | tr -d '[:space:]')"
printf '  archiver last_archived_wal: %s (lifetime failed_count %s)\n' "$last_archived" "$failed"

printf '\n===== 7. recoverable boundary =====\n'
boundary="$(psql_query "SELECT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')||'+00'")"
cat <<SUMMARY

  final archived segment : $final_segment
  boundary timestamp     : $boundary

  Everything committed before this point is recoverable, and the runtime roles
  can no longer authenticate, so nothing can add to it by accident.

  Do NOT run --unfence until the migration is abandoned. Restoring login
  authority here lets Airflow reconnect and write past the boundary, and those
  writes will not exist on the new primary.

  On the new host:

    ./infra/scripts/pgbackrest-restore.sh --promote

  with no --target, which restores to the end of the archive and therefore to
  exactly this boundary. Use --target "$boundary" only if later WAL exists that
  you deliberately want to exclude.

  This host stays fenced. Revoke its AWS identity only after the new host is
  verified and serving.

  To abandon the migration and resume here:

    ./infra/scripts/cutover-fence.sh --unfence
    ./infra/scripts/compose-with-bitwarden.sh up -d

SUMMARY
info "fenced; PostgreSQL is still running for inspection, and no runtime role can log in"
