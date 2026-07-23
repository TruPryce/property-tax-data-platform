#!/usr/bin/env bash
set -euo pipefail
IFS=$'\n\t'

BWRAP=/usr/bin/bwrap
PROFILE_PATH=/etc/apparmor.d/countyforge-bwrap
PROFILE_NAME=countyforge-bwrap
EXPECTED_RESTRICT_VALUE=1

err() { printf 'ERROR: %s\n' "$*" >&2; }
info() { printf '==> %s\n' "$*"; }

print_apparmor_status() {
  printf 'apparmor_profile=%s\n' "$PROFILE_NAME" >&2
  printf 'bwrap_path=%s\n' "$BWRAP" >&2
  if [[ -e "$BWRAP" ]]; then
    printf 'bwrap_resolved=%s\n' "$(readlink -f "$BWRAP" 2>/dev/null || printf 'unresolved')" >&2
    printf 'bwrap_owner=%s\n' "$(stat -c '%u:%g' "$BWRAP" 2>/dev/null || printf 'unknown')" >&2
    "$BWRAP" --version >&2 || true
  fi
  printf 'apparmor_restrict_unprivileged_userns=%s\n' "$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns 2>/dev/null || printf 'unavailable')" >&2
  printf 'unprivileged_userns_clone=%s\n' "$(cat /proc/sys/kernel/unprivileged_userns_clone 2>/dev/null || printf 'unavailable')" >&2
  printf 'max_user_namespaces=%s\n' "$(cat /proc/sys/user/max_user_namespaces 2>/dev/null || printf 'unavailable')" >&2
  if command -v aa-status >/dev/null 2>&1; then
    aa-status --enabled >/dev/null 2>&1 && printf 'apparmor_enabled=true\n' >&2 || printf 'apparmor_enabled=false\n' >&2
  else
    printf 'aa_status=unavailable\n' >&2
  fi
}

fail_with_status() {
  err "$*"
  print_apparmor_status
  exit 2
}

if [[ ! -x "$BWRAP" ]]; then
  fail_with_status "$BWRAP is unavailable or not executable"
fi

BWRAP_RESOLVED="$(readlink -f "$BWRAP")"
if [[ "$BWRAP_RESOLVED" != "$BWRAP" ]]; then
  fail_with_status "$BWRAP resolves unexpectedly to $BWRAP_RESOLVED"
fi

BWRAP_OWNER="$(stat -c '%u:%g' "$BWRAP")"
if [[ "$BWRAP_OWNER" != "0:0" ]]; then
  fail_with_status "$BWRAP is not root-owned (owner $BWRAP_OWNER)"
fi

if ! command -v apparmor_parser >/dev/null 2>&1; then
  fail_with_status "apparmor_parser is unavailable"
fi

if [[ -r /proc/sys/kernel/apparmor_restrict_unprivileged_userns ]]; then
  CURRENT_RESTRICT_VALUE="$(cat /proc/sys/kernel/apparmor_restrict_unprivileged_userns)"
  if [[ "$CURRENT_RESTRICT_VALUE" != "$EXPECTED_RESTRICT_VALUE" ]]; then
    fail_with_status "kernel.apparmor_restrict_unprivileged_userns must remain $EXPECTED_RESTRICT_VALUE (found $CURRENT_RESTRICT_VALUE)"
  fi
else
  fail_with_status "kernel.apparmor_restrict_unprivileged_userns is unavailable"
fi

info "Installing CountyForge Bubblewrap AppArmor profile for $BWRAP"
PROFILE_TMP="$(mktemp)"
cleanup() { rm -f "$PROFILE_TMP"; }
trap cleanup EXIT
cat > "$PROFILE_TMP" <<'PROFILE'
abi <abi/4.0>,
include <tunables/global>

profile countyforge-bwrap /usr/bin/bwrap flags=(unconfined) {
  userns,
}
PROFILE

sudo install -o root -g root -m 0644 "$PROFILE_TMP" "$PROFILE_PATH"
sudo apparmor_parser -r -W "$PROFILE_PATH"

info "CountyForge Bubblewrap AppArmor profile loaded"
print_apparmor_status

# Mandatory capability probe for the requested child command:
#   bwrap --unshare-net -- /usr/bin/true
# Bubblewrap starts from an empty root, so bind the fixed runtime roots read-only to make
# /usr/bin/true and its loader visible. This mirrors the broker's existing read-only runtime
# mounts without changing the broker's sandbox flags or mounted host surfaces.
PROBE_ARGS=(--unshare-net)
for runtime_root in /usr /usr/local /bin /lib /lib64 /opt /etc; do
  if [[ -e "$runtime_root" ]]; then
    PROBE_ARGS+=(--ro-bind "$runtime_root" "$runtime_root")
  fi
done
PROBE_ARGS+=(-- /usr/bin/true)
set +e
PROBE_STDERR="$($BWRAP "${PROBE_ARGS[@]}" 2>&1)"
PROBE_STATUS=$?
set -e
if [[ "$PROBE_STATUS" -ne 0 ]]; then
  err "Bubblewrap AppArmor capability probe failed (exit $PROBE_STATUS)"
  if [[ -n "$PROBE_STDERR" ]]; then
    printf 'probe_stderr_begin\n' >&2
    printf '%s\n' "$PROBE_STDERR" | head -20 >&2
    printf 'probe_stderr_end\n' >&2
  fi
  print_apparmor_status
  exit "$PROBE_STATUS"
fi

info "Bubblewrap AppArmor capability probe passed"
