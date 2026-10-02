# Development guide

## Local environment

```bash
uv sync --all-extras          # or: make install  (Python 3.12 venv in .venv from uv.lock)
make up                       # PostgreSQL + the rest of the stack
make lint                     # ruff check, ruff format --check, mypy --strict
make test                     # unit + integration against the compose PostgreSQL
```

Running the CLI from your shell against the compose database:

```bash
set -a; source .env; set +a
export RDP_DB_HOST=127.0.0.1 RDP_DB_PORT=$POSTGRES_PORT RDP_DB_NAME=$WAREHOUSE_DB_NAME \
       RDP_DB_USER=$WAREHOUSE_DB_USER RDP_DB_PASSWORD=$WAREHOUSE_DB_PASSWORD \
       RDP_SOURCE_MODE=replay RDP_LOG_FORMAT=console
uv run rdp db migrate
uv run rdp ingest api --run-id dev-1
uv run rdp transform --run-id dev-1 --select stg_api_products+
uv run rdp pipeline run
uv run streamlit run dashboard/app.py
```

`Settings` reads `RDP_*` variables (and a local `.env`). The full list, with defaults, is in
`src/retail_data_platform/config/settings.py`. The compose-level variables are documented in
`.env.example`.

## Tests

| Suite | Needs | Command |
|---|---|---|
| Unit (`tests/unit`) | nothing | `make test-unit` |
| Integration (`tests/integration`) | PostgreSQL; user with CREATEDB (`RDP_TEST_DB_*`) | `make test` |
| DAG integrity (`tests/airflow`) | Airflow image | `make test-dags` |
| dbt | PostgreSQL | part of `rdp transform` / the end-to-end test |

Integration tests create a throw-away database (`rdp_test_<random>`) and drop it afterwards. If
no server is reachable they are **skipped**, not failed. CI always provides one. No test
contacts a third-party website. Unit tests use `httpx.MockTransport`, and parser tests use the
committed HTML fixtures. The `live` marker is reserved for opt-in checks against the real sites.

## Replay fixtures

`data/fixtures/dummyjson/products.json` and `data/fixtures/books_toscrape/**.html` follow the
public JSON schema and HTML markup of the real sites (`article.product_pod`, `p.price_color`,
`p.star-rating <Word>`, `li.next > a`, sidebar `ul.nav-list`). They were hand-assembled to
mirror that structure, because the build environment could not reach the live sites. The
replay transports emulate DummyJSON's `limit`/`skip` pagination and serve the HTML tree by path.
When a live site changes, save the new page or response as a fixture and update the parser
until the tests pass again.

## Adding a new source

1. Create `src/retail_data_platform/ingestion/<kind>/<name>.py` with a class that has a
   `source` attribute and implements `extract() -> Iterator[SourceRecord]` and
   `normalize(record) -> ProductObservation`. Raise `SourceSchemaError` for structural breakage,
   and let Pydantic raise for record-level violations.
2. Add the value to `SourceName`, a raw table in a **new** migration
   (`database/migrations/0003_<name>.sql`; never edit an applied migration, because checksums are
   verified), and an entry in `RAW_TABLES`.
3. Register it in `ingestion/registry.py` (and a replay transport if it uses HTTP).
4. dbt: declare the source, add `stg_<name>_products` with the canonical column set, add it to
   the union in `int_product_observations`, and add rows to the `source_catalog`,
   `category_mapping` and (if needed) `currency_rates` seeds.
5. Airflow: add an `ingest_<name>` task, plus fixture-based unit tests and an integration case.

## Conventions

- Business logic lives in the package. Airflow tasks are one CLI call each.
- New schema changes go in a new migration file. Migrations are applied in order and verified
  by checksum.
- Logging uses `get_logger()` with bound context. `print()` is banned by Ruff (`T20`).
- Type hints are mandatory (`mypy --strict` on `src/`).
- Commits are small and coherent, using conventional prefixes (`feat`, `fix`, `test`, `docs`,
  `ci`, `build`).

## Building behind a TLS-intercepting proxy

Corporate networks that re-sign TLS break `pip`/`uv` inside image builds. The Dockerfiles
accept an optional BuildKit secret, `ca_bundle`, used only during dependency installation and
never stored in a layer:

```bash
docker build --secret id=ca_bundle,src=/path/to/corp-ca.pem \
  --build-arg HTTPS_PROXY=$HTTPS_PROXY --network host -f docker/app.Dockerfile --target cli .
```

With Compose, add the same settings in an override file (`build.secrets`, `build.args`,
`build.network`) and keep that file out of git.
