# Data Pipeline: LinkedIn Connections

## Context

This document describes the ETL data pipeline which processes LinkedIn connection data exported from LinkedIn's "Download Your Data" feature. The pipeline imports CSV files containing connection information including names, profile URLs, companies, positions, and connection dates.

The goal of this pipeline is to maintain a database of LinkedIn connections with historical tracking of connection status changes, enabling analytics on professional network growth and composition.

The data includes:

| Column | Description | Example |
|--------|-------------|---------|
| **First Name** | Connection's first name | John |
| **Last Name** | Connection's last name | Doe |
| **URL** | LinkedIn profile URL (unique identifier) | https://www.linkedin.com/in/johndoe |
| **Email Address** | Email if shared by connection | john@example.com |
| **Company** | Company/organization | Acme Inc |
| **Position** | Job title | Software Engineer |
| **Connected On** | Date connection was established | 09 Jan 2026 |

### CSV Format Notes

- Lines 1-2 contain LinkedIn notes/headers
- Line 4 contains column headers
- Date format: "DD Mon YYYY" (e.g., "09 Jan 2026")
- Fields may be empty (Email Address, Company, Position)

### How to Export from LinkedIn

1. Go to **Settings & Privacy** → **Data privacy** → **Get a copy of your data**
2. Select **Connections** (and any other data you want)
3. Click **Request archive**
4. LinkedIn will email you a download link (usually within 24 hours)
5. Download and extract the ZIP file
6. The `Connections.csv` file contains your connection data

## Airflow DAG

* [DAG code](dag.py)

* DAG schedule: **Manual trigger only** (`dag_schedule_interval=None`)

* DAG ID: `linkedin`

* Task dependency: `ingest >> batch >> process >> store`

The DAG uses [`ETLConfig`](../../lib/etl_config.py) that defines file types from [`LINKEDIN_FILE_TYPES`](constants.py), processing parameters (`max_process_tasks=1`, `min_file_sets_in_batch=1`), and applies the default task sequence using `apply_default_task_sequence=True`.

**Triggering the DAG:**

Since this pipeline has no automatic schedule, trigger it manually via the Airflow UI:

1. Navigate to the `linkedin` DAG in Airflow
2. Click "Trigger DAG"
3. Click "Trigger" to start processing

**Data Directory:**

Files should be manually deposited in the `ingest` directory:

- **diegotower**: `/home/diegoscarabelli/repos/openetl/data/linkedin/ingest/`
- **Local (Astro)**: `data/linkedin/ingest/`

### Ingest task

The ingest task utilizes the standard `ingest()` function from the [Standard DAG](../../../README.md#standard-dag) pattern. It moves files matching the `Connections.*\.csv$` pattern from the ingest directory to the process directory for downstream batching and processing.

### Batch task

The batch task uses the standard `batch()` function from the [Standard DAG](../../../README.md#standard-dag) pattern with default configuration:

* Groups files by timestamp into processing batches using [`LINKEDIN_FILE_TYPES`](constants.py) for file type coordination
* **Parameter**: `min_file_sets_in_batch=1`: sets the minimum number of file sets required in a batch to 1
* **Parameter**: `max_process_tasks=1`: single concurrent processing task (typical for manual-trigger pipelines)

### Process task

[Code](process.py)

The custom process task uses the [`LinkedInProcessor`](process.py) class that inherits from the base [`Processor`](../../lib/dag_utils.py#Processor) class. It provides specialized processing logic for LinkedIn connection CSV files.

**Processing Flow:**

The `process_file_set` method of [`LinkedInProcessor`](process.py) orchestrates processing of connection CSV files:

1. **CSV Parsing** ([`_parse_csv_file`](process.py)): Locates the header row containing "First Name" and parses subsequent data rows using Python's `csv.DictReader`.

2. **Date Parsing** ([`_parse_date`](process.py)): Converts LinkedIn date format "DD Mon YYYY" (e.g., "09 Jan 2026") to Python `date` objects.

3. **Capture Date Extraction** ([`_extract_capture_date`](process.py)): Extracts the export date from the filename (e.g., `Connections_20260110.csv` → `2026-01-10`). This date is stored with each record to prevent stale data from older exports overwriting newer data.

4. **Connection Processing** ([`_process_connections_file`](process.py)):
   - Creates `Connection` model instances for each row with valid URL
   - Sets `active_connection=True` and `capture_date` for all connections
   - Uses [`upsert_model_instances`](../../lib/sql_utils.py#upsert_model_instances) to insert or update the `linkedin.connection` table (defined in [`tables.ddl`](tables.ddl)) with `["url"]` as the conflict column
   - Updates: `first_name`, `last_name`, `email_address`, `company`, `position`, `connected_on`, `active_connection`, `capture_date`
   - Uses `latest_check_column="capture_date"` with `latest_check_inclusive=True` to only update records when the file's capture date is newer than or equal to the existing record

5. **Inactive Marking** ([`_mark_inactive_connections`](process.py)):
   - Queries active connections with `capture_date` older than or equal to the current file
   - Sets `active_connection=False` for connections in DB but not in current file
   - Enables tracking of removed connections over time

**Database Upsert Method:**

* [`upsert_model_instances`](../../lib/sql_utils.py#upsert_model_instances) with `on_conflict_update=True` using `["url"]` as the conflict column
* Uses `latest_check_column="capture_date"` with `latest_check_inclusive=True` to prevent older exports from overwriting newer data
* When reprocessing, updates all connection data except `url` (the unique identifier) only if the file's `capture_date` is newer than or equal to the existing record

### Store task

The store task uses the standard `store()` function from the [Standard DAG](../../../README.md#standard-dag) pattern with default implementation. Processed files are moved from the process directory to the store directory.

