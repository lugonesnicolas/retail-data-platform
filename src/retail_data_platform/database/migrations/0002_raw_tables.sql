-- Bronze layer: append-only, one table per source.
-- Canonical typed columns satisfy the ingestion contract; raw_payload keeps full source fidelity.
-- record_hash makes reloads idempotent (INSERT ... ON CONFLICT DO NOTHING).
create schema if not exists raw;

create table if not exists raw.api_products (
    id                 bigint generated always as identity primary key,
    record_hash        char(64)      not null unique,
    source_run_id      uuid          not null references ops.source_runs (source_run_id),
    pipeline_run_id    text,
    source_product_id  text          not null,
    product_name       text          not null,
    brand              text,
    category           text,
    price              numeric(12, 2) not null check (price >= 0),
    currency           char(3)       not null,
    availability       text          not null,
    rating             numeric(3, 2),
    product_url        text,
    observed_at        timestamptz   not null,
    ingested_at        timestamptz   not null,
    loaded_at          timestamptz   not null default now(),
    source_url         text,
    raw_payload        jsonb         not null
);
comment on table raw.api_products is 'DummyJSON products API (one row per product per observation day/state).';
create index if not exists api_products_product_observed_idx on raw.api_products (source_product_id, observed_at);
create index if not exists api_products_loaded_at_idx on raw.api_products (loaded_at);

create table if not exists raw.web_products (
    id                 bigint generated always as identity primary key,
    record_hash        char(64)      not null unique,
    source_run_id      uuid          not null references ops.source_runs (source_run_id),
    pipeline_run_id    text,
    source_product_id  text          not null,
    product_name       text          not null,
    brand              text,
    category           text,
    price              numeric(12, 2) not null check (price >= 0),
    currency           char(3)       not null,
    availability       text          not null,
    rating             numeric(3, 2),
    product_url        text,
    observed_at        timestamptz   not null,
    ingested_at        timestamptz   not null,
    loaded_at          timestamptz   not null default now(),
    source_url         text,
    raw_payload        jsonb         not null
);
comment on table raw.web_products is 'books.toscrape.com category listings.';
create index if not exists web_products_product_observed_idx on raw.web_products (source_product_id, observed_at);
create index if not exists web_products_loaded_at_idx on raw.web_products (loaded_at);

create table if not exists raw.dataset_products (
    id                 bigint generated always as identity primary key,
    record_hash        char(64)      not null unique,
    source_run_id      uuid          not null references ops.source_runs (source_run_id),
    pipeline_run_id    text,
    source_product_id  text          not null,
    product_name       text          not null,
    brand              text,
    category           text,
    price              numeric(12, 2) not null check (price >= 0),
    currency           char(3)       not null,
    availability       text          not null,
    rating             numeric(3, 2),
    product_url        text,
    observed_at        timestamptz   not null,
    ingested_at        timestamptz   not null,
    loaded_at          timestamptz   not null default now(),
    source_url         text,
    raw_payload        jsonb         not null
);
comment on table raw.dataset_products is 'Versioned retail CSV dataset (data/sample/retail_products.csv).';
create index if not exists dataset_products_product_observed_idx on raw.dataset_products (source_product_id, observed_at);
create index if not exists dataset_products_loaded_at_idx on raw.dataset_products (loaded_at);

-- Records that violated the contract. Never silently dropped.
create table if not exists raw.rejected_records (
    id                 bigint generated always as identity primary key,
    source             text        not null,
    source_run_id      uuid        not null references ops.source_runs (source_run_id),
    pipeline_run_id    text,
    source_record_ref  text,
    source_url         text,
    errors             jsonb       not null,
    raw_payload        jsonb       not null,
    rejected_at        timestamptz not null default now()
);

create index if not exists rejected_records_source_idx on raw.rejected_records (source, rejected_at desc);
