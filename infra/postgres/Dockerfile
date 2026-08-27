ARG POSTGRES_VERSION=16.11
FROM postgres:${POSTGRES_VERSION}-bookworm

# Exact package version, not a range. Debian Bookworm ships pgBackRest 2.45,
# which has no `process` S3 key type and therefore cannot use the keyless
# Roles Anywhere credentials this repository is reached with. The official
# postgres image already configures apt.postgresql.org, which carries 2.59.1;
# the `=` pin plus the version assertion below means an upstream bump fails the
# build instead of arriving silently in a rebuild.
ARG PGBACKREST_VERSION=2.59.1-1.pgdg12+1
ARG PGBACKREST_EXPECTED_VERSION=2.59.1

# Pinned by digest rather than by "latest for 1.8.4": a release asset can be
# re-uploaded under the same version string, and a backup tool's credential
# helper is the wrong place to trust that it will not be.
ARG SIGNING_HELPER_VERSION=1.8.4
ARG SIGNING_HELPER_SHA256=b7568acd6e1517a4e1adaee68d52bfd6284a0e5305677166cd83d43a07c815c9

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        "pgbackrest=${PGBACKREST_VERSION}" \
        ca-certificates \
        curl; \
    installed="$(pgbackrest version | awk '{print $2}')"; \
    if [ "$installed" != "$PGBACKREST_EXPECTED_VERSION" ]; then \
        echo "error: pgBackRest ${installed} installed, expected ${PGBACKREST_EXPECTED_VERSION}" >&2; \
        exit 1; \
    fi; \
    curl -fsSL -o /usr/local/bin/aws_signing_helper \
        "https://rolesanywhere.amazonaws.com/releases/${SIGNING_HELPER_VERSION}/X86_64/Linux/Amzn2023/aws_signing_helper"; \
    echo "${SIGNING_HELPER_SHA256}  /usr/local/bin/aws_signing_helper" | sha256sum -c -; \
    chmod 0555 /usr/local/bin/aws_signing_helper; \
    apt-get purge -y --auto-remove curl; \
    rm -rf /var/lib/apt/lists/*

# The certificate group must exist INSIDE the image with postgres as a member.
#
# Compose's `group_add` sets supplementary groups on the container's initial
# process, but the postgres entrypoint starts as root and then switches to the
# postgres user, which re-derives supplementary groups from this image's
# /etc/group and drops everything Docker added. The result is subtle: `docker
# exec --user postgres` keeps the added group and can read the key, so every
# check an operator runs by hand passes, while the archiver -- a child of the
# postmaster -- runs without it and cannot read the certificate at all.
#
# That failure is not quiet. archive-push exits 103, PostgreSQL treats the dead
# archive command as a crash, and the cluster enters a restart loop. Measured on
# the deployed runtime before this line existed.
ARG TRUPRYCE_AWS_GID=2000
RUN set -eux; \
    groupadd --gid "${TRUPRYCE_AWS_GID}" trupryce-certificates; \
    usermod --append --groups trupryce-certificates postgres; \
    id postgres

# Owned by postgres because archive_command runs as a child of the backend, and
# a directory root can write but postgres cannot is an archive that fails only
# under load, when the spool is first actually used.
RUN set -eux; \
    mkdir -p /var/log/pgbackrest /var/spool/pgbackrest /etc/pgbackrest; \
    chown -R postgres:postgres /var/log/pgbackrest /var/spool/pgbackrest /etc/pgbackrest; \
    chmod 0750 /var/log/pgbackrest /var/spool/pgbackrest

COPY --chmod=0444 infra/postgres/pgbackrest/pgbackrest.conf /etc/pgbackrest/pgbackrest.conf
COPY --chmod=0555 infra/postgres/pgbackrest/aws-signing-process.sh /usr/local/bin/pgbackrest-aws-signing

# The whole directory, so the lexicographic convention is real: the entrypoint
# runs every .sh and .sql here in filename order, and adding 20-*.sql needs no
# change to this file. Copying one named script would have made the documented
# ordering a fiction that failed silently.
COPY --chmod=0555 infra/postgres/init/ /docker-entrypoint-initdb.d/
