#!/usr/bin/env bash
# Install the pgBackRest backup timers, resolving host-specific values.
#
# The committed units are templates because a durable unit definition must not
# carry one host's operator account or home directory: a replacement VPS -- the
# whole point of the S3 recovery boundary -- would inherit a path that does not
# exist there and fail at the first timer fire, silently, because a timer that
# cannot start its service is not an obvious outage.
#
# Run as root. Everything host-specific is resolved here and nowhere else.
set -euo pipefail

SERVICE_USER="${SERVICE_USER:-${SUDO_USER:-}}"
REPOSITORY_DIR="${REPOSITORY_DIR:-}"
UNIT_DIR="${UNIT_DIR:-/etc/systemd/system}"
CERTIFICATE_GID="${CERTIFICATE_GID:-2000}"

die() { printf 'install-systemd-units: %s\n' "$*" >&2; exit 2; }

[[ "$(id -u)" -eq 0 ]] || die "must run as root to write $UNIT_DIR"

if [[ -z "$REPOSITORY_DIR" ]]; then
    REPOSITORY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)"
fi
[[ -n "$SERVICE_USER" ]] || die "set SERVICE_USER to the account that owns the Docker socket access"
id "$SERVICE_USER" >/dev/null 2>&1 || die "no such user: $SERVICE_USER"
[[ -x "$REPOSITORY_DIR/infra/scripts/pgbackrest-backup.sh" ]] \
    || die "not a repository checkout: $REPOSITORY_DIR"

# The unit needs the Docker socket, so the service user must already be able to
# reach it. Checked rather than granted: adding a user to the docker group is a
# privilege decision for an operator, not a side effect of installing a timer.
DOCKER_GROUP="$(stat -c '%G' /var/run/docker.sock 2>/dev/null || echo docker)"
if ! id -nG "$SERVICE_USER" | tr ' ' '\n' | grep -qx "$DOCKER_GROUP"; then
    die "$SERVICE_USER is not in the '$DOCKER_GROUP' group and could not reach the Docker socket"
fi

# The certificate group must exist with the GID the Compose file passes as a
# supplementary group, or the container joins a GID that grants nothing. Shared
# with install-certificate-identity.sh so the two cannot disagree, and fails
# closed rather than adopting a GID that already belongs to another group.
# shellcheck source=lib/certificate-group.sh
source "$REPOSITORY_DIR/infra/scripts/lib/certificate-group.sh"
require_certificate_group "$CERTIFICATE_GID" || die "certificate group contract not satisfied"

for kind in full diff; do
    template="$REPOSITORY_DIR/infra/systemd/pgbackrest-${kind}.service.template"
    [[ -r "$template" ]] || die "missing template: $template"
    sed \
        -e "s|@@SERVICE_USER@@|${SERVICE_USER}|g" \
        -e "s|@@DOCKER_GROUP@@|${DOCKER_GROUP}|g" \
        -e "s|@@REPOSITORY_DIR@@|${REPOSITORY_DIR}|g" \
        "$template" > "${UNIT_DIR}/pgbackrest-${kind}.service"
    chmod 0644 "${UNIT_DIR}/pgbackrest-${kind}.service"

    install -m 0644 "$REPOSITORY_DIR/infra/systemd/pgbackrest-${kind}.timer" \
        "${UNIT_DIR}/pgbackrest-${kind}.timer"
done

# Fail before enabling rather than after: an unsubstituted placeholder would
# otherwise become a timer that starts and immediately fails once a week.
if grep -l '@@' "${UNIT_DIR}"/pgbackrest-*.service >/dev/null 2>&1; then
    die "unsubstituted placeholder left in an installed unit"
fi

systemctl daemon-reload
systemctl enable --now pgbackrest-full.timer pgbackrest-diff.timer
systemctl list-timers 'pgbackrest-*' --no-pager

printf 'install-systemd-units: installed for user=%s repository=%s\n' \
    "$SERVICE_USER" "$REPOSITORY_DIR" >&2
