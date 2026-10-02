# syntax=docker/dockerfile:1.7
# Airflow (LocalExecutor) image. The platform package and dbt live in an isolated virtualenv
# (/opt/rdp) so their dependencies never conflict with Airflow's constraint-pinned environment;
# DAG tasks invoke the `rdp` CLI from that virtualenv.

ARG AIRFLOW_IMAGE=apache/airflow:3.3.2-python3.12
ARG PYTHON_IMAGE=python:3.12-slim-bookworm
ARG UV_VERSION=0.8.17

FROM ${PYTHON_IMAGE} AS uv
ARG UV_VERSION
RUN --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/ca_bundle ]; then export PIP_CERT=/run/secrets/ca_bundle; fi; \
    pip install --no-cache-dir "uv==${UV_VERSION}"

FROM ${AIRFLOW_IMAGE}
USER root
COPY --from=uv /usr/local/bin/uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/rdp
WORKDIR /opt/rdp-src
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=secret,id=ca_bundle,required=false \
    --mount=type=cache,target=/root/.cache/uv \
    if [ -f /run/secrets/ca_bundle ]; then export SSL_CERT_FILE=/run/secrets/ca_bundle; fi; \
    uv sync --frozen --no-dev --extra dbt --no-install-project --python /usr/python/bin/python3
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --extra dbt --no-editable --python /usr/python/bin/python3 \
    && ln -sf /opt/rdp/bin/rdp /usr/local/bin/rdp \
    && ln -sf /opt/rdp/bin/dbt /usr/local/bin/dbt \
    && rm -rf /opt/rdp-src /usr/local/bin/uv

COPY --chown=airflow:root dbt /opt/rdp-project/dbt
COPY --chown=airflow:root data/sample /opt/rdp-project/data/sample
COPY --chown=airflow:root data/fixtures /opt/rdp-project/data/fixtures
COPY --chown=airflow:root airflow/dags /opt/airflow/dags

ENV RDP_DBT_PROJECT_DIR=/opt/rdp-project/dbt \
    RDP_DBT_PROFILES_DIR=/opt/rdp-project/dbt \
    RDP_DBT_TARGET_PATH=/tmp/dbt/target \
    RDP_DBT_LOG_PATH=/tmp/dbt/logs \
    RDP_DATASET_PATH=/opt/rdp-project/data/sample/retail_products.csv \
    RDP_FIXTURES_DIR=/opt/rdp-project/data/fixtures
WORKDIR /opt/airflow
USER airflow
