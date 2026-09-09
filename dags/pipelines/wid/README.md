# Data Pipeline: World Inequality Database (WID)

## Context

This document describes the ETL data pipeline that ingests the complete World Inequality Database (WID) into the `lens` database as a star schema. The pipeline downloads WID's public bulk ZIP, unpacks its per-country CSVs, and loads them into the `wid` schema.

The goal of this pipeline is to maintain a complete, queryable copy of WID (all ~141M observations plus WID's aggregate entities) for analytics, refreshed from WID's roughly annual bulk release.

The bulk ZIP (`https://wid.world/bulk_download/wid_all_data.zip`, ~850 MB) is the single source; no WID API calls are made. It has been verified to be a complete superset of WID's REST API (all observations plus aggregate entities the API omits), so a single offline conversion reproduces everything.

### Source Files

Three kinds of semicolon-delimited CSV files are read from the ZIP:

| File | Grain | Contents |
|------|-------|----------|
| `WID_data_<country>.csv` | per country | Observations: `country;variable;percentile;year;value;age;pop` |
| `WID_metadata_<country>.csv` | per country | Variable metadata at `(country, sixlet, age, pop)` grain |
| `WID_countries.csv` | global | Entity names and regions |

Notes:

- Each file has a header row and uses `;` as the delimiter.
- The data `variable` column is WID's native variable code: the packed `sixlet + pop + age` string (e.g. `sptincj992`). It is used verbatim as `variable_code`. The first six characters are the `sixlet` (a one-letter series type plus a five-letter concept); the explicit `age` and `pop` columns repeat the packed age and population parts.
- The `percentile` column (e.g. `p99p100`, or a g-percentile point such as `p99`) is a separate dimension and a column on the fact table, not part of the variable code.
- Metadata concept-level fields (name, description, unit, long labels) feed the `variable` dimension; the country-specific `source`, `method`, and `data_quality_score` feed the `provenance` dimension.
- The WID bulk export pairs each country's data file with a metadata file.

### Target Schema (`wid`)

The pipeline loads a star schema (defined in [`tables.ddl`](tables.ddl)). A time series is identified by `(variable_code, percentile_code)`, and a single observation by `(country_code, variable_code, percentile_code, year)`:

- `observation` (fact, ~141M rows): `country_code, variable_code, percentile_code, year, value`; primary key `(country_code, variable_code, percentile_code, year)`. A plain PostgreSQL table (not a TimescaleDB hypertable): WID is replaced in full each release, which does not fit the append-only model hypertable compression optimizes for.
- `variable` (dimension): keyed by the native `variable_code` (e.g. `sptincj992`), unpacked into `series_type`, `concept`, `age_code`, and `pop_code`, plus a generated `sixlet` column (`series_type || concept`) and concept-level metadata (`short_name`, `description`, `technical_description`, `unit`, `long_type`, `long_pop`, `long_age`). One row per native code, independent of percentile.
- `percentile` (dimension): keyed by `percentile_code`, with `is_range`, `lower_bound`, `upper_bound`, and `width`. Two kinds of code occur: explicit ranges (`p99p100` → the bracket [99, 100]) and WID g-percentile points used by average series (`p99` → the group [99, next), whose upper bound is the next percentile point present in the data, which is the next g-percentile in a full load). Populated by the `finalize` task from the codes present in the loaded data.
- `country` (dimension): `country_code`, `name`, `region`.
- `provenance` (dimension): country-specific `source`, `method`, and `data_quality_score`, keyed by `(country_code, variable_code)` (WID provides these once per country and variable, not per percentile).

## Airflow DAG

* [DAG code](dag.py)

* DAG schedule: **Manual trigger only** (`dag_schedule_interval=None`); WID releases roughly once a year.

* DAG ID: `wid`

* Task dependency: `extract >> ingest >> batch >> prepare >> process >> finalize >> store`

The DAG uses [`ETLConfig`](../../lib/etl_config.py) with file types from [`WID_FILE_TYPES`](constants.py), processing parameters (`max_process_tasks=8`, `min_file_sets_in_batch=1`), and a custom task sequence (`apply_default_task_sequence=False`) so the custom `extract`, `prepare`, and `finalize` tasks can bracket the standard `ingest`/`batch`/`process`/`store` sequence.

Each run is a full reload: `prepare` truncates the `observation` table before the load, so a run is idempotent at the run level and there is no separate backfill mode. Because the load appends (it does not replace per country), it is not idempotent to stale working files: if a prior run failed and left files in the `process` directory, re-running without clearing them re-appends those rows. This does not corrupt data silently (the `finalize` primary-key build fails on the resulting duplicates), but after a failed run clear the working directories (`ingest`/`process`) before re-triggering.

**Triggering the DAG:**

Since this pipeline has no automatic schedule, trigger it manually via the Airflow UI:

1. Navigate to the `wid` DAG in Airflow
2. Click "Trigger DAG"
3. Click "Trigger" to start processing

A single run downloads the current ZIP and replaces all countries.

**Prerequisites:**

- The `wid` schema, tables, and the `airflow_wid` user must exist (see [`schemas.ddl`](../../schemas.ddl), [`tables.ddl`](tables.ddl), and [`iam.sql`](../../iam.sql)). `airflow_wid` owns the `observation` table so the pipeline can drop and rebuild its constraints and index.
- An `airflow_wid.json` credential file in the directory named by `SQL_CREDENTIALS_DIR`.

### Extract task

[Code](extract.py)

The custom extract task downloads the WID bulk ZIP and unpacks the per-country data and metadata CSVs (plus the countries CSV) into the ingest directory. Each country's data and metadata files are written with a shared ISO-8601 timestamp so `batch` groups them into one FileSet; the countries CSV gets its own timestamp. The download retries with exponential backoff (up to `MAX_RETRIES`) and verifies the payload (Content-Length, ZIP magic bytes, and central-directory integrity). It can be skipped to reuse already-downloaded files via DAG run config `{"task_ids_to_skip": ["extract"]}`.

### Ingest task

The ingest task uses the standard `ingest()` function from the [Standard DAG](../../../README.md#standard-dag) pattern. It moves the extracted WID CSVs from the ingest directory to the process directory for downstream batching and processing.

### Batch task

The batch task uses the standard `batch()` function from the [Standard DAG](../../../README.md#standard-dag) pattern:

* Groups files by timestamp into FileSets using [`WID_FILE_TYPES`](constants.py): one FileSet per country (its data + metadata files) plus a separate countries FileSet.
* **Parameter** `min_file_sets_in_batch=1`: a batch needs at least one FileSet.
* **Parameter** `max_process_tasks=8`: country FileSets are fanned out across up to 8 parallel process tasks.

### Prepare task

[Code](process.py)

The custom prepare task ([`prepare_observation_table`](process.py)) drops the `observation` primary key, foreign keys, and secondary index and truncates the table, so the parallel load runs against an unindexed, constraint-free fact table. It also clears the `percentile` dimension (with `DELETE`, since `airflow_wid` does not own that table) so its data-derived bounds reflect only the current load; `finalize` repopulates it. It runs once, before `process`. See the Finalize task for why the indexes are dropped for the load and rebuilt afterwards.

### Process task

[Code](process.py)

The custom process task uses the [`WidProcessor`](process.py) class that inherits from the base [`Processor`](../../lib/dag_utils.py#Processor) class. It runs per FileSet, in parallel across up to 8 workers.

**Processing Flow:**

The `process_file_set` method handles two kinds of FileSet:

1. **Countries FileSet:** upserts the `country` dimension (names and regions) from `WID_countries.csv` using [`upsert_model_instances`](../../lib/sql_utils.py#upsert_model_instances).

2. **Country FileSet** (one transaction per country):
   - Ensures the country row exists so the observation and provenance foreign keys hold.
   - Upserts the `variable` dimension. The variable dimension is global (keyed by the native `variable_code`) and its concept metadata is country-invariant, so codes are inserted first-writer-wins (`ON CONFLICT DO NOTHING`) in deterministic conflict-key order. The ordering makes concurrent workers acquire the shared variable-index locks in the same order, avoiding a deadlock that would otherwise quarantine a country.
   - Upserts the country's `provenance` rows from the metadata, keyed by `(country_code, variable_code)`. A row is emitted only for variables the country actually has data for, so the `provenance` → `variable` foreign key holds even when the metadata lists variables absent from the data file.
   - Appends the country's observations (including `percentile_code`) into the (truncated, unindexed) `observation` table with PostgreSQL `COPY`, via the [`copy_records`](../../lib/sql_utils.py) helper. There is no per-country `DELETE`; the table was truncated once by `prepare`.

If a country's metadata file is missing, its new variable codes are stored with empty concept metadata and a warning is logged. Because the bulk export pairs data and metadata files, this does not occur in practice.

### Finalize task

[Code](process.py)

The custom finalize task ([`finalize_observation_table`](process.py)) first completes the `percentile` dimension, then rebuilds the `observation` primary key, foreign keys, and secondary index, using a larger `maintenance_work_mem` and parallel maintenance workers.

The `percentile` dimension is populated from the distinct percentile codes present in the loaded observations ([`build_percentile_rows`](process.py) parses each code into numeric bounds). This runs here, after the load and before the observation foreign keys are rebuilt, because a g-percentile point's upper bound is the next present point, which needs the full set of codes in one place.

Maintaining the composite primary key, three foreign keys, and the secondary index on every one of ~141M inserts dominates the load; building the indexes once and validating the foreign keys in a single pass is dramatically faster. The rebuild doubles as a load check: duplicate keys make the primary-key build fail, and orphaned variable, country, or percentile codes make the foreign-key validation fail. Measured end to end on the full ~143M-row dataset, the observation DB work dropped from ~23 minutes (indexed inserts) to ~7.4 minutes (~2.9 minutes to bulk-load the unindexed table, then ~4.6 minutes to rebuild).

### Store task

The store task uses the standard `store()` function from the [Standard DAG](../../../README.md#standard-dag) pattern. Processed files are moved from the process directory to the store directory.
