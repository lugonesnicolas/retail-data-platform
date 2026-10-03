# syntax=docker/dockerfile:1.7
# Application images built from one Dockerfile:
#   --target cli        rdp CLI + dbt (migrations, ad-hoc pipeline runs, smoke tests)
#   --target dashboard  Streamlit dashboard (no dbt)
#
# Optional build secret "ca_bundle" lets the build work behind TLS-intercepting corporate
# proxies; it is mounted only for the install step and never stored in a layer.

ARG PYTHON_IMAGE=python:3.12-slim-bookworm
ARG UV_VERSION=0.8.17

FROM ${PYTHON_IMAGE} AS uv
ARG UV_VERSION
RUN --mount=type=secret,id=ca_bundle,required=false \
    if [ -f /run/secrets/ca_bundle ]; then export PIP_CERT=/run/secrets/ca_bundle; fi; \
    pip install --no-cache-dir "uv==${UV_VERSION}"

# ------------------------------------------------------------------------------- builders
FROM ${PYTHON_IMAGE} AS builder
COPY --from=uv /usr/local/bin/uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/rdp
WORKDIR /src
COPY pyproject.toml uv.lock README.md ./

FROM builder AS build-cli
RUN --mount=type=secret,id=ca_bundle,required=false \
    --mount=type=cache,target=/root/.cache/uv \
    if [ -f /run/secrets/ca_bundle ]; then export SSL_CERT_FILE=/run/secrets/ca_bundle; fi; \
    uv sync --frozen --no-dev --extra dbt --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --extra dbt --no-editable

FROM builder AS build-dashboard
RUN --mount=type=secret,id=ca_bundle,required=false \
    --mount=type=cache,target=/root/.cache/uv \
    if [ -f /run/secrets/ca_bundle ]; then export SSL_CERT_FILE=/run/secrets/ca_bundle; fi; \
    uv sync --frozen --no-dev --extra dashboard --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --extra dashboard --no-editable

# -------------------------------------------------------------------------------- runtimes
FROM ${PYTHON_IMAGE} AS runtime-base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH=/opt/rdp/bin:$PATH
RUN groupadd --system --gid 10001 rdp \
    && useradd --system --uid 10001 --gid rdp --home-dir /app --shell /usr/sbin/nologin rdp
WORKDIR /app

FROM runtime-base AS cli
COPY --from=build-cli /opt/rdp /opt/rdp
COPY --chown=rdp:rdp dbt ./dbt
COPY --chown=rdp:rdp data/sample ./data/sample
COPY --chown=rdp:rdp data/fixtures ./data/fixtures
ENV RDP_DBT_PROJECT_DIR=/app/dbt \
    RDP_DBT_PROFILES_DIR=/app/dbt \
    RDP_DBT_TARGET_PATH=/tmp/dbt/target \
    RDP_DBT_LOG_PATH=/tmp/dbt/logs \
    RDP_DATASET_PATH=/app/data/sample/retail_products.csv \
    RDP_FIXTURES_DIR=/app/data/fixtures
USER rdp
ENTRYPOINT ["rdp"]
CMD ["--help"]

FROM runtime-base AS dashboard
COPY --from=build-dashboard /opt/rdp /opt/rdp
COPY --chown=rdp:rdp dashboard ./dashboard
USER rdp
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=4).status == 200 else 1)"]
ENTRYPOINT ["streamlit", "run", "dashboard/app.py"]
CMD ["--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true", \
     "--browser.gatherUsageStats=false", "--client.toolbarMode=viewer"]
