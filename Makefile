# Developer command interface. Run `make help` for the list of targets.
SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

COMPOSE ?= docker compose
# Extra flags for `docker compose build` (e.g. behind a proxy: --build-arg HTTPS_PROXY=...)
BUILD_FLAGS ?=
-include .env
export

TEST_DB_ENV = RDP_TEST_DB_HOST=127.0.0.1 RDP_TEST_DB_PORT=$(POSTGRES_PORT) \
	RDP_TEST_DB_USER=$(POSTGRES_SUPERUSER) RDP_TEST_DB_PASSWORD=$(POSTGRES_SUPERUSER_PASSWORD)

.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------- environment
.PHONY: setup
setup: ## Create .env with generated secrets (if missing) and build images
	@scripts/generate-env.sh
	$(COMPOSE) build $(BUILD_FLAGS)

.PHONY: install
install: ## Install the local Python dev environment (requires uv)
	uv sync --all-extras

.PHONY: up
up: ## Start the platform and wait until every service is healthy
	$(COMPOSE) up -d --wait

.PHONY: down
down: ## Stop the platform (data volumes are kept)
	$(COMPOSE) --profile observability --profile tools --profile mail down

.PHONY: clean
clean: ## Stop the platform and DELETE all data volumes
	$(COMPOSE) --profile observability --profile tools --profile mail down -v --remove-orphans

.PHONY: ps
ps: ## Show service status
	$(COMPOSE) ps

.PHONY: logs
logs: ## Follow logs of all services
	$(COMPOSE) logs -f --tail=100

# ---------------------------------------------------------------- pipeline
.PHONY: migrate
migrate: ## Apply warehouse migrations
	$(COMPOSE) run --rm tools db migrate

.PHONY: pipeline
pipeline: ## Trigger the Airflow DAG and wait for the result
	scripts/run-dag.sh 900

.PHONY: pipeline-local
pipeline-local: ## Run the same pipeline without Airflow (tools container)
	$(COMPOSE) run --rm tools pipeline run

.PHONY: ingest
ingest: ## Ingest all sources (no dbt)
	$(COMPOSE) run --rm tools ingest all

.PHONY: dbt
dbt: ## dbt build (models + tests) via the tools container
	$(COMPOSE) run --rm tools transform

.PHONY: dbt-docs
WAREHOUSE_ENV = RDP_DB_HOST=127.0.0.1 RDP_DB_PORT=$(POSTGRES_PORT) RDP_DB_NAME=$(WAREHOUSE_DB_NAME) \
	RDP_DB_USER=$(WAREHOUSE_DB_USER) RDP_DB_PASSWORD=$(WAREHOUSE_DB_PASSWORD)

dbt-docs: ## Generate dbt docs + lineage graph and serve them on http://localhost:8081
	$(WAREHOUSE_ENV) uv run dbt docs generate --project-dir dbt --profiles-dir dbt
	$(WAREHOUSE_ENV) uv run dbt docs serve --project-dir dbt --profiles-dir dbt --port 8081 --no-browser

.PHONY: mailpit
mailpit: ## Start the local SMTP catcher for testing alerts (http://localhost:8025)
	$(COMPOSE) --profile mail up -d mailpit

.PHONY: alert-test
alert-test: ## Send a test alert email with the SMTP settings from .env
	$(COMPOSE) run --rm tools alert test

.PHONY: grafana
grafana: ## Start the optional Grafana (http://localhost:3000)
	$(COMPOSE) --profile observability up -d --wait grafana

# ---------------------------------------------------------------- quality
.PHONY: lint
lint: ## Ruff lint + format check + mypy
	uv run ruff check .
	uv run ruff format --check .
	uv run mypy

.PHONY: format
format: ## Auto-format and fix lint
	uv run ruff format .
	uv run ruff check --fix .

.PHONY: test
test: ## Unit + integration tests (integration uses the compose PostgreSQL)
	$(TEST_DB_ENV) uv run pytest --cov --cov-report=term

.PHONY: test-unit
test-unit: ## Unit tests only (no database needed)
	uv run pytest tests/unit

.PHONY: test-dags
test-dags: ## DAG integrity tests inside the Airflow image
	$(COMPOSE) run --rm --no-deps -e RDP_DAGS_DIR=/opt/airflow/dags \
		-v "$(CURDIR)/tests:/opt/rdp-tests/tests:ro" \
		--entrypoint bash airflow-scheduler -c \
		"pip install -q --user pytest && cd /opt/rdp-tests && python -m pytest -q -p no:cacheprovider -o addopts='' --confcutdir=tests/airflow tests/airflow"

.PHONY: smoke
smoke: ## Smoke-test marts, dashboard and Airflow of the running stack
	$(COMPOSE) run --rm tools smoke --dashboard-url http://dashboard:8501 --airflow-url http://airflow-apiserver:8080
