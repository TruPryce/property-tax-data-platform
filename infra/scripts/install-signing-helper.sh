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

command -v sha256sum >/dev/null 2>&1 || die "sha256sum is required"

# Accept an existing binary only on its DIGEST, never on the version string it
# prints. A version string is output from the very program whose integrity is in
# question, so a replaced or corrupted binary that answers "1.8.4" would
# otherwise be adopted without inspection -- for the executable that turns the
# workload private key into AWS credentials.
#
# Digest-checked before the download tooling, so re-running on an
# already-provisioned host still succeeds without curl present.
if [[ -x "$INSTALL_PATH" ]]; then
    existing_digest="$(sha256sum "$INSTALL_PATH" | cut -d' ' -f1)"
    installed_version="$("$INSTALL_PATH" version 2>/dev/null || true)"
    if [[ "$existing_digest" == "$SIGNING_HELPER_SHA256" ]]; then
        # Correct bytes are not enough. If the file or its directory is writable
        # by anyone but root, the digest just verified says nothing about what
        # will run next -- and what runs next turns the workload private key
        # into AWS credentials. Reinstall to fix ownership and mode rather than
        # accepting it.
        existing_owner="$(stat -c '%u:%g' "$INSTALL_PATH")"
        existing_mode="$(stat -c '%a' "$INSTALL_PATH")"
        directory_mode="$(stat -c '%a' "$(dirname "$INSTALL_PATH")")"
        if [[ "$existing_owner" == "0:0" ]] \
            && (( (8#$existing_mode & 022) == 0 )) \
            && (( (8#$directory_mode & 022) == 0 )); then
            info "$INSTALL_PATH already at $SIGNING_HELPER_VERSION (digest verified, root-owned, not writable)"
            exit 0
        fi
        info "$INSTALL_PATH has the right digest but weak permissions"
        info "  owner $existing_owner mode $existing_mode, directory mode $directory_mode"
        info "reinstalling to restore root:root and a non-writable mode"
    elif [[ "$installed_version" == "$SIGNING_HELPER_VERSION" ]]; then
        # The dangerous case, called out explicitly: right version, wrong bytes.
        info "$INSTALL_PATH reports $SIGNING_HELPER_VERSION but its digest does not match the pin"
        info "  expected $SIGNING_HELPER_SHA256"
        info "  found    $existing_digest"
        info "replacing it"
    else
        info "replacing $INSTALL_PATH (found '${installed_version:-unknown}', want $SIGNING_HELPER_VERSION)"
    fi
fi

command -v curl >/dev/null 2>&1 || die "curl is required"

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
