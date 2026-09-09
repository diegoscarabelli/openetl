# WID Pipeline

Ingests the complete World Inequality Database (WID) into the `lens` database as a star
schema. The pipeline downloads WID's public bulk ZIP, unpacks its per-country CSVs, and
loads them into the `wid` schema: an `observation` fact table plus `country`, `variable`,
and `provenance` dimensions. The bulk ZIP is the single source; no WID API calls are
made.

## Source data

WID publishes one bulk ZIP (`https://wid.world/bulk_download/wid_all_data.zip`, ~850 MB)
that contains the entire database as per-country CSVs. It has been verified to be a
complete superset of WID's REST API (all observations plus aggregate entities the API
omits), so a single offline conversion reproduces everything.

Three kinds of files are read from the ZIP:

- `WID_data_<country>.csv` (per country): observations. Columns
  `country;variable;percentile;year;value;age;pop`, where `variable` is the packed
  `sixlet + pop + age` string (e.g. `sptincj992`). The fully qualified variable code is
  `sixlet_percentile_age_pop`.
- `WID_metadata_<country>.csv` (per country): variable metadata at
  `(country, sixlet, age, pop)` grain. Concept-level fields (name, description, unit,
  and long labels) feed the `variable` dimension; the country-specific `source`,
  `method`, and `data_quality_score` feed the `provenance` dimension.
- `WID_countries.csv` (global): entity names and regions for the `country` dimension.

## Schema (`wid`)

- `observation` (fact, ~141M rows): `country_code, variable_code, year, value`; primary
  key `(country_code, variable_code, year)`. A plain PostgreSQL table (not a hypertable):
  WID is replaced in full each annual release, which does not fit TimescaleDB's
  append-only compression model.
- `variable` (dimension): the fully qualified code unpacked into `sixlet`, `series_type`,
  `concept`, `age_code`, `pop_code`, and `percentile`, plus concept-level metadata
  (`short_name`, `description`, `technical_description`, `unit`, `long_type`, `long_pop`,
  `long_age`).
- `country` (dimension): `country_code`, `name`, `region`.
- `provenance` (dimension): country-specific `source`, `method`, and
  `data_quality_score`, keyed by `(country_code, sixlet, age_code, pop_code)`.

## DAG

Tasks: `extract -> ingest -> batch -> prepare -> process -> finalize -> store`. Manual
trigger only (`dag_schedule_interval=None`); WID releases roughly once a year.

- `extract`: downloads the bulk ZIP and unpacks the per-country data and metadata CSVs
  (plus the countries CSV) into the ingest directory. Each country's two files share a
  timestamp so `batch` groups them into one FileSet; the countries CSV gets its own.
- `ingest` / `batch`: standard framework tasks. One FileSet per country (data +
  metadata), plus a countries FileSet.
- `prepare`: drops the observation primary key and foreign keys and truncates the table
  so the load runs against an unindexed, constraint-free fact table.
- `process` (parallel per country): in one transaction, upsert the country row, its
  variables, and its provenance, then append the country's observations with `COPY`. The
  countries FileSet fills country names and regions. Processing is order-independent.
- `finalize`: rebuilds the observation primary key and foreign keys.
- `store`: standard framework task.

Each run is a full reload (`prepare` truncates before the load), so the pipeline is
idempotent at the run level and there is no separate backfill mode.

## Load method

Each run rebuilds the observation fact table from scratch, and the primary key and
foreign keys are dropped for the load and rebuilt afterwards. Maintaining the composite
key and checking two foreign keys on every one of ~141M inserts dominates the runtime;
loading into an unindexed table and building the key once (with the foreign keys
validated in a single pass) is dramatically faster. Measured on ~143M rows: the indexed
insert path takes ~20 minutes, versus ~30s to bulk-load plus ~3.5 minutes to build the
key and ~20s to validate the foreign keys.

The rebuild doubles as a load check: duplicate keys make the primary key build fail, and
orphaned variable or country codes make the foreign-key validation fail. Dimensions
(`country`, `variable`, `provenance`) keep their keys and are loaded with
`upsert_model_instances`; observations are loaded with PostgreSQL `COPY` via the
`copy_records` helper in `dags/lib/sql_utils.py`.

## Prerequisites

- The `wid` schema, tables, and the `airflow_wid` user must exist (see `dags/schemas.ddl`,
  `dags/pipelines/wid/tables.ddl`, and `dags/iam.sql`).
- An `airflow_wid.json` credential file in `SQL_CREDENTIALS_DIR`.

## Running

Trigger the `wid` DAG manually from the Airflow UI or CLI. A single run downloads the
current ZIP and replaces all countries.
