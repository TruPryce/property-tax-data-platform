#!/usr/bin/env bash
# Run a pgBackRest backup inside the Compose-managed PostgreSQL container.
#
# Invoked by systemd timers on the host. Scheduling lives on the host and not
# in Airflow because Airflow's own metadata database is one of the two
# databases this protects: a backup that stops when Airflow stops is missing
# exactly when it is needed.
#
# Execution stays in the container because archive_command runs as a child of
# the PostgreSQL backend, so pgBackRest has to see PGDATA in the same namespace.
set -euo pipefail

COMPOSE_PROJECT="${COMPOSE_PROJECT:-property-tax-platform}"
COMPOSE_SERVICE="${COMPOSE_SERVICE:-postgres}"
STANZA="${PGBACKREST_STANZA:-platform}"

usage() {
    printf 'usage: %s <full|diff|incr|check|info>\n' "${0##*/}" >&2
    exit 2
}

[[ $# -eq 1 ]] || usage
action="$1"
case "$action" in
    full | diff | incr | check | info) ;;
    *) usage ;;
esac

# Selected by Compose label, never by container ID or name. An ID changes on
# every recreate and a name can pick up a different numeric suffix, so a unit
# that hardcodes either keeps running and silently backs up nothing the first
# time the stack is rebuilt -- which is precisely when nobody is watching.
# `com.docker.compose.oneoff=False` is the discriminator that matters.
# `docker compose build` bakes project and service labels into the *image*, so
# every container started from it -- including an isolated PITR restore --
# inherits them and matches a project/service filter. Only a container Compose
# actually ran carries oneoff. Measured: during the recorded restore exercise
# the two-label filter matched both the production cluster and the temporary
# recovery cluster.
mapfile -t containers < <(
    docker ps --quiet \
        --filter "label=com.docker.compose.project=${COMPOSE_PROJECT}" \
        --filter "label=com.docker.compose.service=${COMPOSE_SERVICE}" \
        --filter "label=com.docker.compose.oneoff=False"
)

if [[ ${#containers[@]} -eq 0 ]]; then
    printf '%s: no running container for %s/%s\n' \
        "${0##*/}" "$COMPOSE_PROJECT" "$COMPOSE_SERVICE" >&2
    exit 3
fi

if [[ ${#containers[@]} -gt 1 ]]; then
    # Ambiguity is a failure, not a coin flip: backing up the wrong cluster
    # succeeds loudly and protects nothing.
    printf '%s: %d containers match %s/%s; refusing to guess\n' \
        "${0##*/}" "${#containers[@]}" "$COMPOSE_PROJECT" "$COMPOSE_SERVICE" >&2
    exit 3
fi

container="${containers[0]}"

case "$action" in
    check | info)
        exec docker exec --user postgres "$container" \
            pgbackrest --stanza="$STANZA" "$action"
        ;;
    *)
        exec docker exec --user postgres "$container" \
            pgbackrest --stanza="$STANZA" --type="$action" backup
        ;;
esac
