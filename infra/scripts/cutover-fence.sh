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

psql_query() {
    docker exec "$container" psql -U platform_admin -d postgres -tAc "$1"
}

printf '\n===== 1. fence writers =====\n'
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

printf '\n===== 2. confirm the database is quiescent =====\n'
# Deliberately excludes this session and PostgreSQL's own background workers.
# Anything else still connected is a writer nobody fenced.
remaining="$(psql_query "
SELECT coalesce(string_agg(DISTINCT usename || '@' || coalesce(client_addr::text,'local') || ' (' || datname || ')', ', '), '')
FROM pg_stat_activity
WHERE pid <> pg_backend_pid()
  AND backend_type = 'client backend'
  AND usename IS NOT NULL")"

if [[ -n "$remaining" ]]; then
    printf '  still connected: %s\n' "$remaining"
    die "clients are still connected; fence them before taking the boundary"
fi
printf '  no client backends remain\n'

writes_before="$(psql_query "SELECT pg_current_wal_lsn()")"
printf '  current WAL LSN: %s\n' "$writes_before"

printf '\n===== 3. flush the final WAL segment =====\n'
final_segment="$(psql_query "SELECT pg_walfile_name(pg_switch_wal())" | tr -d '[:space:]')"
printf '  switched: %s\n' "$final_segment"

printf '\n===== 4. wait for it to reach S3 =====\n'
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

printf '\n===== 5. recoverable boundary =====\n'
boundary="$(psql_query "SELECT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')||'+00'")"
cat <<SUMMARY

  final archived segment : $final_segment
  boundary timestamp     : $boundary

  Everything committed before this point is recoverable. Nothing may be written
  on this host from now until cutover completes -- restarting Airflow would
  create writes that the new primary will not have.

  On the new host:

    ./infra/scripts/pgbackrest-restore.sh --promote

  with no --target, which restores to the end of the archive and therefore to
  exactly this boundary. Use --target "$boundary" only if later WAL exists that
  you deliberately want to exclude.

  This host stays fenced. Revoke its identity only after the new host is
  verified and serving.

SUMMARY
info "fenced; PostgreSQL is still running so it can be inspected, but nothing should write to it"
