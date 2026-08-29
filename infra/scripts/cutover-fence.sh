#!/usr/bin/env bash
# Freeze the source: fence every writer, archive the final WAL, stop PostgreSQL,
# and report the WAL segment that is now the durable cutover boundary.
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

bitwarden_environment_file="${BWS_ENV_FILE:-$infra_dir/.bws.env}"
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

# role:database:bitwarden-secret. Activation proves the credential that the
# runtime will actually present, which is a different claim from "the role may
# log in" -- see the comment on prove_runtime_credentials.
RUNTIME_CREDENTIALS=(
    "airflow_metadata:airflow:AIRFLOW_DB_PASSWORD"
    "property_tax_migrator:property_tax:PROPERTY_TAX_MIGRATOR_PASSWORD"
    "property_tax_ingestion:property_tax:PROPERTY_TAX_INGESTION_PASSWORD"
    "property_tax_api:property_tax:PROPERTY_TAX_API_PASSWORD"
)

# Prove each runtime identity can actually authenticate, with the password the
# runtime will use.
#
# `psql -U role` inside the container reaches PostgreSQL over the Unix socket,
# which pg_hba maps to `trust`. That proves NOLOGIN was lifted and nothing more.
# It cannot detect the case that matters for disaster recovery: a restore whose
# recovery point predates a password rotation, where rolcanlogin is true, the
# cluster is healthy, and every runtime service still fails to connect because
# Bitwarden holds a newer secret the restored cluster never received.
#
# So this connects to the container's own non-loopback address, which matches
# `host all all all scram-sha-256`, and supplies the Bitwarden password by
# reference -- `-e PGPASSWORD` with no value, so it never enters argv.
prove_runtime_credentials() {
    local address entry role database secret password ok=true
    address="$(docker inspect "$container" \
        --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' 2>/dev/null)"
    if [[ -z "$address" ]]; then
        die "could not determine the container address for a TCP credential check"
    fi

    [[ -f "$bitwarden_environment_file" ]] || die "missing $bitwarden_environment_file"
    local token project
    token="$(grep -E '^BWS_ACCESS_TOKEN=' "$bitwarden_environment_file" | tail -n 1)"; token="${token#*=}"
    project="$(grep -E '^BWS_PROJECT_ID=' "$bitwarden_environment_file" | tail -n 1)"; project="${project#*=}"
    [[ -n "$token" && -n "$project" ]] || die "Bitwarden access token and project ID are required"

    for entry in "${RUNTIME_CREDENTIALS[@]}"; do
        role="${entry%%:*}"
        database="${entry#*:}"; database="${database%%:*}"
        secret="${entry##*:}"

        password="$(BWS_ACCESS_TOKEN="$token" bws run --project-id "$project" --no-inherit-env \
            -- printenv "$secret" 2>/dev/null)"
        if [[ -z "$password" ]]; then
            printf '  %s: could not resolve %s from Bitwarden\n' "$role" "$secret"
            ok=false
            continue
        fi

        if PGPASSWORD="$password" docker exec -e PGPASSWORD -i "$container" \
            psql -h "$address" -U "$role" -d "$database" -tAc 'SELECT 1' >/dev/null 2>&1; then
            printf '  %s -> %s: authenticated with the stored credential\n' "$role" "$database"
        else
            printf '  %s -> %s: CREDENTIAL REJECTED\n' "$role" "$database"
            ok=false
        fi
        password=""
    done
    $ok
}

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

    printf '\n===== 2. prove LOGIN authority was restored =====\n'
    local activated=true
    for role in "${RUNTIME_ROLES[@]}"; do
        if [[ "$(psql_query "SELECT rolcanlogin FROM pg_roles WHERE rolname = '$role'" \
                 | tr -d '[:space:]')" == "t" ]]; then
            printf '  %s: LOGIN authority restored\n' "$role"
        else
            printf '  %s: STILL NOLOGIN\n' "$role"
            activated=false
        fi
    done
    $activated || die "activation incomplete; a runtime role still cannot log in"

    printf '\n===== 3. prove the stored credentials actually authenticate =====\n'
    prove_runtime_credentials \
        || die "a runtime credential was rejected; the restored cluster's passwords do not match
    Bitwarden, most likely because the recovery point predates a rotation. Reconcile
    with ALTER ROLE ... PASSWORD before starting the runtime."

    printf '\n===== 4. archive the activation =====\n'
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
    info "activated; all four runtime credentials authenticate and the transition is archived"
    info "now start the rest of the runtime: ./infra/scripts/compose-with-bitwarden.sh up -d"
    exit 0
}

[[ "${1:-}" == "--unfence" ]] && unfence

printf '\n===== 1. confirm the source backup schedule is stopped =====\n'
# A fenced source is not a frozen one. Once the timers from task 4c.2 are
# installed, the old primary keeps its own backup schedule -- so after Hostinger
# promotes onto a new timeline, a scheduled Akamai backup can still land in the
# same stanza on the old timeline and become the newest backup in the
# repository. That is a worse outcome than the migration failing.
#
# Checked rather than stopped: disabling a systemd unit needs root this script
# does not hold, and stopping an operator's backup schedule is their decision.
active_timers=""
if command -v systemctl >/dev/null 2>&1; then
    active_timers="$(systemctl list-units --no-legend --no-pager \
        'pgbackrest-*.timer' 'pgbackrest-*.service' 2>/dev/null \
        | awk '$3 == "active" || $4 == "running" {print $1}' | tr '\n' ' ')"
fi
if [[ -n "$active_timers" ]]; then
    printf '  active: %s\n' "$active_timers"
    die "the source backup schedule is still active. Stop it before freezing, or a
    scheduled backup of the old primary can land in the stanza after the new host
    has branched onto its own timeline:
      sudo systemctl disable --now pgbackrest-full.timer pgbackrest-diff.timer"
fi
printf '  no pgbackrest timer or service is active\n'

printf '\n===== 2. stop known writers =====\n'
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

printf '\n===== 3. revoke login authority =====\n'
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

printf '\n===== 4. terminate existing sessions =====\n'
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

printf '\n===== 5. prove a fresh login now fails =====\n'
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

printf '\n===== 6. flush the final WAL segment =====\n'
final_segment="$(psql_query "SELECT pg_walfile_name(pg_switch_wal())" | tr -d '[:space:]')"
printf '  switched: %s\n' "$final_segment"

printf '\n===== 7. wait for it to reach S3 =====\n'
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

# Read while the cluster is still up, and used only for correlating with logs.
# The authoritative boundary is the segment above, not this.
boundary_observed="$(psql_query "SELECT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')||'+00'")"

printf '\n===== 8. stop the source cluster =====\n'
# Stopped before the boundary is reported, not after. A running postmaster keeps
# generating and archiving WAL -- checkpoints, autovacuum, platform_admin
# sessions -- so any boundary printed while it still ran would already be stale
# by the time it was read. Reporting "frozen" before the stop had succeeded was
# the same mistake in miniature.
docker stop "$container" >/dev/null || die "could not stop $container; the source is NOT frozen"
printf '  stopped %s\n' "$container"

# Prove it, rather than trusting the exit status of the stop.
if [[ -n "$(postgres_container)" ]]; then
    die "$container is still running; the source is NOT frozen"
fi
printf '  confirmed stopped; the archive can no longer advance\n'

printf '\n===== 9. durable cutover boundary =====\n'
cat <<SUMMARY

  SOURCE FROZEN. PostgreSQL is stopped and the archive cannot advance.

  durable boundary : $final_segment
      This WAL segment is the boundary. It is the last segment confirmed present
      in S3 while writers were fenced, and nothing can be added after it. It is
      the boundary because it is a fact about the archive, not about a clock.

  observed at      : $boundary_observed   (informational only)
      A wall-clock reading, useful for correlating with logs. It is NOT a safe
      PITR target: a timestamp later than the last commit makes recovery fail
      with "recovery ended before configured recovery target was reached", and
      on a quiet database that is most timestamps.

  On the new host, with no target at all:

    ./infra/scripts/pgbackrest-restore.sh --promote

  That restores to the end of the archive, which is now fixed at the segment
  above because this source can no longer write to it. Do not pass --target for
  a planned migration; it can only exclude data you meant to keep.

  Then activate before starting the runtime:

    ./infra/scripts/compose-with-bitwarden.sh up -d postgres
    ./infra/scripts/cutover-fence.sh --unfence
    ./infra/scripts/compose-with-bitwarden.sh up -d

  Revoke this host's AWS identity only after the new host is verified and
  serving -- it is still needed if the migration is abandoned.

  To abandon the migration and resume here, in this order:

    ./infra/scripts/compose-with-bitwarden.sh up -d postgres
    ./infra/scripts/cutover-fence.sh --unfence
    sudo systemctl enable --now pgbackrest-full.timer pgbackrest-diff.timer
    ./infra/scripts/compose-with-bitwarden.sh up -d

SUMMARY
info "frozen; durable boundary is segment $final_segment"
