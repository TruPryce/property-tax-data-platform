ARG AIRFLOW_VERSION=3.3.0
ARG PYTHON_VERSION=3.12
FROM apache/airflow:${AIRFLOW_VERSION}-python${PYTHON_VERSION}

ARG AIRFLOW_VERSION

COPY --chown=airflow:0 libs/property-tax-domain /opt/property-tax/libs/property-tax-domain
COPY --chown=airflow:0 libs/property-tax-application /opt/property-tax/libs/property-tax-application
COPY --chown=airflow:0 libs/property-tax-adapters /opt/property-tax/libs/property-tax-adapters
COPY --chown=airflow:0 services/ingestion-worker /opt/property-tax/services/ingestion-worker

RUN pip install --no-cache-dir \
      "apache-airflow==${AIRFLOW_VERSION}" \
      /opt/property-tax/libs/property-tax-domain \
      /opt/property-tax/libs/property-tax-application \
      /opt/property-tax/libs/property-tax-adapters \
      /opt/property-tax/services/ingestion-worker \
 && test "$(airflow version)" = "${AIRFLOW_VERSION}" \
 && property-tax-ingestion counties >/dev/null
