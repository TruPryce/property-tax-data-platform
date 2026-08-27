#!/usr/bin/env bash
# Report how long the workload certificate has left.
#
# This is a signal, not monitoring. Nothing runs it on a schedule and nothing
# alerts on it; observability is not implemented by this change. It exists
# because an expired certificate stops credential exchange, which stops WAL
# archiving, and that failure looks exactly like a backup that quietly stopped
# running -- so the one thing worth having early is a command that answers the
# question directly.
#
# Exits 0 when comfortably valid, 1 inside the warning window, 2 when expired or
# unreadable, so it is usable from a timer or CI job once something watches it.
set -euo pipefail

CERTIFICATE="${TRUPRYCE_AWS_CERTIFICATE:-/etc/trupryce/aws/trupryce-data-platform-vps.pem}"
WARN_DAYS="${WARN_DAYS:-30}"

if [[ ! -r "$CERTIFICATE" ]]; then
    printf 'check-certificate-expiry: cannot read %s\n' "$CERTIFICATE" >&2
    exit 2
fi

subject="$(openssl x509 -in "$CERTIFICATE" -noout -subject)"
not_after="$(openssl x509 -in "$CERTIFICATE" -noout -enddate)"
not_after="${not_after#notAfter=}"

expires_at="$(date -u -d "$not_after" +%s)"
now="$(date -u +%s)"
days_left=$(( (expires_at - now) / 86400 ))

printf '  certificate : %s\n' "$CERTIFICATE"
printf '  %s\n' "$subject"
printf '  not after   : %s\n' "$not_after"
printf '  days left   : %s\n' "$days_left"

if (( days_left < 0 )); then
    printf '  status      : EXPIRED -- credential exchange is failing and WAL is not archiving\n'
    exit 2
fi
if (( days_left <= WARN_DAYS )); then
    printf '  status      : RENEW NOW -- within %s days of expiry\n' "$WARN_DAYS"
    printf '  renewal     : see docs/operations/postgresql-recovery.md section 2.6\n'
    exit 1
fi
printf '  status      : ok\n'
