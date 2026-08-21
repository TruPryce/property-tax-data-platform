ARG POSTGRES_VERSION=16.11
FROM postgres:${POSTGRES_VERSION}-bookworm

# The whole directory, so the lexicographic convention is real: the entrypoint
# runs every .sh and .sql here in filename order, and adding 20-*.sql needs no
# change to this file. Copying one named script would have made the documented
# ordering a fiction that failed silently.
COPY --chmod=0555 infra/postgres/init/ /docker-entrypoint-initdb.d/
