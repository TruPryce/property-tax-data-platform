# Shared certificate-group contract. Sourced by every installer that touches
# the certificate directory, so the two cannot disagree about what the GID means.
#
# The naive form is a silent privilege leak:
#
#     if getent group "$gid" >/dev/null; then :; else groupadd --gid "$gid" ...; fi
#
# On a fresh host that number may already belong to something else -- Debian and
# Ubuntu hand out 1000+ to ordinary user groups, so `developers:x:2000:alice,bob`
# is entirely plausible. The check passes, and the installer then chgrps the
# Roles Anywhere private key to `developers` at 0640, granting every member of an
# unrelated group the ability to assume the platform's AWS identity.
#
# So: the name and the number must agree, or nothing happens.

CERTIFICATE_GROUP_NAME="${CERTIFICATE_GROUP_NAME:-trupryce-certificates}"

# require_certificate_group <gid>
#
#   name exists at that gid          -> accept
#   name exists at a different gid   -> fail (configuration disagrees with the host)
#   gid belongs to another group     -> fail (never adopt a stranger's group)
#   neither exists                   -> create the name at that gid
require_certificate_group() {
    local gid="$1"
    local existing_gid existing_name

    if ! [[ "$gid" =~ ^[0-9]+$ ]]; then
        printf 'certificate group: GID must be numeric, got %s\n' "$gid" >&2
        return 2
    fi

    existing_gid="$(getent group "$CERTIFICATE_GROUP_NAME" | cut -d: -f3)"
    existing_name="$(getent group "$gid" | cut -d: -f1)"

    if [[ -n "$existing_gid" ]]; then
        if [[ "$existing_gid" != "$gid" ]]; then
            printf 'certificate group: %s exists with GID %s but the configuration says %s\n' \
                "$CERTIFICATE_GROUP_NAME" "$existing_gid" "$gid" >&2
            printf 'certificate group: refusing to proceed; reconcile TRUPRYCE_AWS_GID with the host\n' >&2
            return 2
        fi
        printf 'certificate group: %s present at GID %s\n' "$CERTIFICATE_GROUP_NAME" "$gid" >&2
        return 0
    fi

    if [[ -n "$existing_name" ]]; then
        printf 'certificate group: GID %s already belongs to group %s\n' "$gid" "$existing_name" >&2
        printf 'certificate group: refusing to grant private-key access to an unrelated group\n' >&2
        printf 'certificate group: choose an unused GID in TRUPRYCE_AWS_GID, or rename that group\n' >&2
        return 2
    fi

    groupadd --gid "$gid" "$CERTIFICATE_GROUP_NAME"
    printf 'certificate group: created %s (%s)\n' "$CERTIFICATE_GROUP_NAME" "$gid" >&2
}
