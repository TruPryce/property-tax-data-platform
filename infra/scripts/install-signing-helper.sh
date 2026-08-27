#!/usr/bin/env bash
# Install the pinned IAM Roles Anywhere signing helper on the HOST.
#
# The PostgreSQL image installs its own copy for pgBackRest. This one is for the
# host's AWS CLI profiles, whose `credential_process` invokes
# /usr/local/bin/aws_signing_helper directly. On a fresh server that binary does
# not exist, so every `aws --profile trupryce-backup ...` command in the runbook
# fails before it can prove anything -- including the identity checks that gate
# the rest of the bootstrap.
#
# Pinned by version AND digest. A release asset can be re-uploaded under the
# same version string, and the thing being installed exchanges a private key for
# AWS credentials.
set -euo pipefail

SIGNING_HELPER_VERSION="${SIGNING_HELPER_VERSION:-1.8.4}"
SIGNING_HELPER_SHA256="${SIGNING_HELPER_SHA256:-b7568acd6e1517a4e1adaee68d52bfd6284a0e5305677166cd83d43a07c815c9}"
INSTALL_PATH="${INSTALL_PATH:-/usr/local/bin/aws_signing_helper}"

die() { printf 'install-signing-helper: %s\n' "$*" >&2; exit 2; }
info() { printf 'install-signing-helper: %s\n' "$*" >&2; }

[[ "$(id -u)" -eq 0 ]] || die "must run as root to write $INSTALL_PATH"

# Checked before the download tooling, so re-running on an already-provisioned
# host succeeds without requiring curl to be present.
if [[ -x "$INSTALL_PATH" ]]; then
    installed="$("$INSTALL_PATH" version 2>/dev/null || true)"
    if [[ "$installed" == "$SIGNING_HELPER_VERSION" ]]; then
        info "$INSTALL_PATH already at $SIGNING_HELPER_VERSION"
        exit 0
    fi
    info "replacing $INSTALL_PATH (found '${installed:-unknown}', want $SIGNING_HELPER_VERSION)"
fi

command -v curl >/dev/null 2>&1 || die "curl is required"
command -v sha256sum >/dev/null 2>&1 || die "sha256sum is required"

# x86_64 only, matching the pinned digest. A different architecture needs its own
# digest, so fail rather than install something unverified.
architecture="$(uname -m)"
[[ "$architecture" == "x86_64" ]] \
    || die "no pinned digest for $architecture; add one before installing"

temporary="$(mktemp)"
trap 'rm -f "$temporary"' EXIT

url="https://rolesanywhere.amazonaws.com/releases/${SIGNING_HELPER_VERSION}/X86_64/Linux/Amzn2023/aws_signing_helper"
info "downloading $SIGNING_HELPER_VERSION"
curl -fsSL -o "$temporary" "$url" || die "download failed: $url"

echo "${SIGNING_HELPER_SHA256}  ${temporary}" | sha256sum -c - >/dev/null \
    || die "checksum mismatch; refusing to install"

install -m 0555 -o root -g root "$temporary" "$INSTALL_PATH"
info "installed $INSTALL_PATH version $("$INSTALL_PATH" version)"
