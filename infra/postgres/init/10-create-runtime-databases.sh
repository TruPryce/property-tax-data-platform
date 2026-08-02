#!/usr/bin/env bash
set -Eeuo pipefail

required_variables=(
  AIRFLOW_DB_PASSWORD
  PROPERTY_TAX_MIGRATOR_PASSWORD
  PROPERTY_TAX_INGESTION_PASSWORD
  PROPERTY_TAX_API_PASSWORD
)

for variable_name in "${required_variables[@]}"; do
  if [[ -z "${!variable_name:-}" ]]; then
    echo "required database credential is missing: ${variable_name}" >&2
    exit 2
  fi
done

psql \
  --set=ON_ERROR_STOP=1 \
  --set=airflow_password="$AIRFLOW_DB_PASSWORD" \
  --set=migrator_password="$PROPERTY_TAX_MIGRATOR_PASSWORD" \
  --set=ingestion_password="$PROPERTY_TAX_INGESTION_PASSWORD" \
  --set=api_password="$PROPERTY_TAX_API_PASSWORD" \
  --username "$POSTGRES_USER" \
  --dbname postgres <<'SQL'
DO $roles$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'airflow_metadata') THEN
    CREATE ROLE airflow_metadata LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'property_tax_migrator') THEN
    CREATE ROLE property_tax_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'property_tax_ingestion') THEN
    CREATE ROLE property_tax_ingestion LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
  END IF;
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'property_tax_api') THEN
    CREATE ROLE property_tax_api LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
  END IF;
END
$roles$;

ALTER ROLE airflow_metadata PASSWORD :'airflow_password';
ALTER ROLE property_tax_migrator PASSWORD :'migrator_password';
ALTER ROLE property_tax_ingestion PASSWORD :'ingestion_password';
ALTER ROLE property_tax_api PASSWORD :'api_password';

SELECT 'CREATE DATABASE airflow OWNER airflow_metadata'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'airflow')\gexec

SELECT 'CREATE DATABASE property_tax OWNER property_tax_migrator'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'property_tax')\gexec

REVOKE CONNECT ON DATABASE airflow FROM PUBLIC;
GRANT CONNECT ON DATABASE airflow TO airflow_metadata;
REVOKE CONNECT ON DATABASE property_tax FROM PUBLIC;
GRANT CONNECT ON DATABASE property_tax TO property_tax_migrator;
GRANT CONNECT ON DATABASE property_tax TO property_tax_ingestion;
GRANT CONNECT ON DATABASE property_tax TO property_tax_api;

\connect airflow
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

\connect property_tax
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
