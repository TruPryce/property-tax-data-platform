ARG POSTGRES_VERSION=16.11
FROM postgres:${POSTGRES_VERSION}-bookworm

COPY --chmod=0555 infra/postgres/init/10-create-runtime-databases.sh /docker-entrypoint-initdb.d/
