# Data Pipeline: Garmin Connect

## Context

This document describes the ETL data pipeline which processes data sourced from Garmin Connect. The pipeline collects comprehensive health, fitness, and activity data using the [python-garminconnect](https://github.com/cyberjunky/python-garminconnect) library, a robust Python SDK that provides comprehensive access to Garmin's ecosystem. The library leverages the [Garth library](https://github.com/matin/garth) underneath to handle complex OAuth 1.0/2.0 authentication flows, multi-factor authentication (MFA) challenges, intelligent session management, and efficient HTTP request pooling to Garmin's servers.

The goal of this pipeline is to support downstream data consumers in generating analytics that provide insights into personal health metrics, training performance, sleep quality, and activity tracking for comprehensive wellness monitoring and optimization.

The data includes:

| Dataset | Content | API Endpoint | Example |
|-------------|--------|-------------|---------------|
| **Sleep** | Sleep stage duration, movement, levels, restless moments, heart rate (redundant with Heart Rate dataset), stress levels (redundant with Stress dataset), body battery (redundant with Stress dataset), HRV (5 mins interval time series), breathing disruptions count (event time-series), detailed scores, and sleep need. | `/wellness-service/wellness/dailySleepData/{display_name}?date={date}&nonSleepBufferMinutes=60` | [15007510_SLEEP_2025-08-07T12:00:00Z.json](./example_data/15007510_SLEEP_2025-08-07T12:00:00Z.json) |
| **Stress** | Stress level and body battery measurements (3 mins interval time-series). | `/wellness-service/wellness/dailyStress/{date}` | [15007510_STRESS_2025-08-07T12:00:00Z.json](./example_data/15007510_STRESS_2025-08-07T12:00:00Z.json) |
| **Respiration** | Breathing rate readings (2 mins interval and 1 hour aggregates time-series) and aggregated statistics. | `/wellness-service/wellness/daily/respiration/{date}` | [15007510_RESPIRATION_2025-08-07T12:00:00Z.json](./example_data/15007510_RESPIRATION_2025-08-07T12:00:00Z.json) |
| **Heart Rate (HR)** | Heart rate readings (2 mins interval time-series). | `/wellness-service/wellness/dailyHeartRate/{display_name}?date={date}` | [15007510_HEART_RATE_2025-08-07T12:00:00Z.json](./example_data/15007510_HEART_RATE_2025-08-07T12:00:00Z.json) |
| **Training Readiness** | Daily training readiness scores (generated multiple times a day) and associated features. | `/metrics-service/metrics/trainingreadiness/{date}` | [15007510_TRAINING_READINESS_2025-08-07T12:00:00Z.json](./example_data/15007510_TRAINING_READINESS_2025-08-07T12:00:00Z.json) |
| **Training Status** | VO2 max (generic and cycling) including heat and altitude acclimation, training load balance (low and high aerobic, anaerobic) with targets, acute/chronic workload ratio (ACWR), and feedback. | `/metrics-service/metrics/trainingstatus/aggregated/{date}` | [15007510_TRAINING_STATUS_2025-08-07T12:00:00Z.json](./example_data/15007510_TRAINING_STATUS_2025-08-07T12:00:00Z.json) |
| **Steps** | Number of steps and activity level (sedentary, sleeping, active, etc.) (15 mins interval time-series). | `/wellness-service/wellness/dailySummaryChart/{display_name}?date={date}` | [15007510_STEPS_2025-08-07T12:00:00Z.json](./example_data/15007510_STEPS_2025-08-07T12:00:00Z.json) |
| **Floors** | Floors climbed and descended (15 mins interval time-series). | `/wellness-service/wellness/floorsChartData/daily/{date}` | [15007510_FLOORS_2025-08-07T12:00:00Z.json](./example_data/15007510_FLOORS_2025-08-07T12:00:00Z.json) |
| **Intensity Minutes** | Weekly and daily moderate/vigorous intensity minutes with time-series data and goal tracking. | `/wellness-service/wellness/daily/im/{date}` | [15007510_INTENSITY_MINUTES_2025-08-07T12:00:00Z.json](./example_data/15007510_INTENSITY_MINUTES_2025-08-07T12:00:00Z.json) |
| **Personal Records** | All-time personal bests steps, running, cycling, swimming, strength. | `/personalrecord-service/personalrecord/prs/{display_name}` | [15007510_PERSONAL_RECORDS_2025-08-07T12:00:00Z.json](./example_data/15007510_PERSONAL_RECORDS_2025-08-07T12:00:00Z.json) |
| **Race Predictions** | Predicted running times based on current fitness level. | `/metrics-service/metrics/racepredictions/latest/{display_name}` | [15007510_RACE_PREDICTIONS_2025-08-07T12:00:00Z.json](./example_data/15007510_RACE_PREDICTIONS_2025-08-07T12:00:00Z.json) |
| **User Profile** | User profile settings including gender, weight, height, birthday, VO2 max (running and cycling), and lactate threshold (speed and heart rate). | `/userprofile-service/userprofile/settings` | [15007510_USER_PROFILE_2025-08-07T12:00:00Z.json](./example_data/15007510_USER_PROFILE_2025-08-07T12:00:00Z.json) |
| **Activities List** | Numerous aggregated metrics for user-recorded activities. | `/activitylist-service/activities/search/activities` | [15007510_ACTIVITIES_LIST_2025-08-07T12:00:00Z.json](./example_data/15007510_ACTIVITIES_LIST_2025-08-07T12:00:00Z.json) |
| **Activity Data (FIT)** | Detailed time-series metrics from sports activities including lap metrics, split metrics, and record-level data with device information. Proprietary binary format optimized for compactness and interoperability. Follows the [FIT Protocol](https://developer.garmin.com/fit/protocol/).| `/download-service/files/activity/{activity_id}` | [15007510_ACTIVITY_19983039914_2025-08-07T12:00:00Z.fit](./example_data/15007510_ACTIVITY_19983039914_2025-08-07T12:00:00Z.fit) |

## Airflow DAG

* [DAG code](dag.py)

* DAG schedule: Daily at 1:00 AM Los Angeles time using `timedelta(days=1)`

* DAG ID: garmin

* Task dependency: `extract >> ingest >> batch >> process >> store`

The DAG uses a custom configuration with [`ETLConfig`](../../lib/etl_config.py) that defines file types from [`GARMIN_FILE_TYPES`](constants.py#GARMIN_FILE_TYPES), processing parameters (`max_process_tasks=3`, `min_file_sets_in_batch=1`), and custom task sequence using `apply_default_task_sequence=False`.

**Data Interval Management with Jinja Templating:**

The extract task uses Jinja templating to dynamically determine the date range for data extraction:

```python
op_kwargs={
    "data_interval_start": (
        "{{ dag_run.conf.get('data_interval_start', "
        "prev_data_interval_end_success) }}"
    ),
    "data_interval_end": (
        "{{ dag_run.conf.get('data_interval_end', " "data_interval_end) }}"
    ),
}
```

* **Schedule**: `timedelta(days=1)` starting at `2008-01-01 01:00:00 America/Los_Angeles`
* **Execution**: Daily at 1:00 AM Los Angeles time
* **Data Interval Behavior**: Each run processes data from the previous day.

**Manual Run Override:**
When triggering manually with custom configuration:
```json
{
  "data_interval_start": "2025-09-15T00:00:00Z",
  "data_interval_end": "2025-09-16T00:00:00Z"
}
```
The Jinja templates will use these custom values instead of the scheduled intervals, allowing for historical data processing or custom date ranges.

**Historical Data Backfill:**

To load historical data when first setting up the pipeline (or to fill gaps), follow these steps:

1. **Comment out the schedule interval** in [`dag.py`](dag.py) to prevent scheduled runs from triggering during backfill:
   ```python
   # dag_schedule_interval=timedelta(days=1),
   ```

2. Trigger a manual DAG run via the Airflow UI:
   - Click the "Trigger DAG" button for the garmin DAG
   - Select **"Single Run"** (NOT "Backfill")
     - **Single Run**: One DAG run processes the entire date range in a single execution
     - **Backfill**: Creates multiple DAG runs (one per schedule interval) - avoid this as it would create thousands of runs for a large date range
   - In the "Configuration JSON" field, specify your desired date range:
     ```json
     {
       "data_interval_start": "2015-01-01T00:00:00Z",
       "data_interval_end": "2025-01-01T00:00:00Z"
     }
     ```
   - Click "Trigger" to start processing

3. **Uncomment the schedule interval** in [`dag.py`](dag.py) after backfill completes to resume normal daily scheduled runs:
   ```python
   dag_schedule_interval=timedelta(days=1),
   ```

The single DAG run will extract and process all Garmin data within the specified period. Note that processing years of historical data may take considerable time, and Garmin API rate limits may apply for very large date ranges.

### Extract task

[Code](extract.py)

The custom extract task uses the [`GarminExtractor`](extract.py) class to download data from Garmin Connect for the specified date range using the [`python-garminconnect`](https://github.com/cyberjunky/python-garminconnect) library. Files are saved with standardized naming conventions to the ingest directory for downstream processing.

**Authentication Integration:**
* OAuth token-based authentication using [`garminconnect`](https://github.com/cyberjunky/python-garminconnect) library with underlying [Garth library](https://github.com/matin/garth) support
* Token storage: `~/.garminconnect/` directory 
* Token refresh utility: [`refresh_garmin_tokens.py`](utility_scripts/refresh_garmin_tokens.py) script for initial setup and yearly refresh
* Multi-Factor Authentication (MFA) support with interactive prompts
* Token lifecycle: Valid for approximately 1 year from creation
* Error handling: Authentication failures trigger detailed troubleshooting instructions referencing the token refresh utility

The task extracts data types defined in [`GARMIN_DATA_REGISTRY`](constants.py#GARMIN_DATA_REGISTRY):

1. **FIT Activity Files**: Downloads binary FIT files for activities within the date range using `download_activity()` method
2. **JSON Wellness Data**: Retrieves 13 different data types using respective API methods defined in the data registry:
   - Daily data types (SLEEP, STRESS, RESPIRATION, etc.) using single date parameters
   - Range data types (ACTIVITIES_LIST) using date range parameters  
   - No-date data types (PERSONAL_RECORDS, RACE_PREDICTIONS, USER_PROFILE) retrieved once per run

The extract function applies conditional end date logic based on whether the start and end dates differ: if `end_date > start_date`, applies exclusive logic (subtracts 1 day from end_date); if `end_date = start_date`, applies inclusive logic (keeps same date).

**Example for September 18, 2025 run:**
* **Scheduled execution time**: 2025-09-18 01:00:00 America/Los_Angeles  
* **data_interval_start**: 2025-09-17 01:00:00 America/Los_Angeles (previous day's execution time)
* **data_interval_end**: 2025-09-18 01:00:00 America/Los_Angeles (current execution time)
* **Extract processing**: Since `end_date > start_date` (Sept 18 > Sept 17), applies **exclusive logic**
* **Actual end_date used**: 2025-09-17 (Sept 18 - 1 day)
* **Data processed**: Garmin data for September 17, 2025 only (single day)

### Ingest task

The ingest task utilizes the standard `ingest()` function from the [Standard DAG](../../../README.md#standard-dag) pattern. It follows the default implementation, handling all extracted files without applying custom regular expressions for direct storage. This ensures consistent ingestion and prepares files for downstream batching and processing.

### Batch task

The batch task uses the standard `batch()` function from the [Standard DAG](../../../README.md#standard-dag) pattern with custom configuration:

* Groups files by timestamp into processing batches using [`GARMIN_FILE_TYPES`](constants.py#GARMIN_FILE_TYPES) for file type coordination
* **Custom parameter**: `min_file_sets_in_batch=1`: sets the minimum number of file sets required in a batch to 1 (the lowest possible limit)
* **Custom parameter**: `max_process_tasks=3`: limits concurrent processing tasks for resource management

### Process task

[Code](process.py)

The custom process task uses the [`GarminProcessor`](process.py) class that inherits from the base [`Processor`](../../lib/dag_utils.py#Processor) class. It provides specialized processing logic for different Garmin data types including user profiles, activities, and health metrics.

**Database Schema Integration:**

* Database tables defined in [`tables.ddl`](tables.ddl)
* TimescaleDB hypertables defined in [`tables_tsdb.ddl`](tables_tsdb.ddl) for time-series data storage and efficient querying
* SQLAlchemy ORM models in [`sqla_models.py`](sqla_models.py) extending base class defined in [`sql_utils.make_base()`](../../lib/sql_utils.py#make_base)

The database schema contains 29 tables organized by category:

**User & Profile (2 tables)**
```
user (root table)
└── user_profile (fitness profile, physical characteristics)
```
*Foreign keys: `user_profile` → `user.user_id`*

**Activities (8 tables)**
```
activity (main activity records)
├── activity_lap_metric (lap-by-lap metrics)
├── activity_split_metric (split data)
├── activity_ts_metric (time-series sensor data)
├── cycling_agg_metrics (cycling-specific aggregates)
├── running_agg_metrics (running-specific aggregates)
├── swimming_agg_metrics (swimming-specific aggregates)
└── supplemental_activity_metric (additional activity metrics)
```
*Foreign keys: `activity` → `user.user_id`; all child tables → `activity.activity_id`*

**Sleep Metrics (6 tables)**
```
sleep (main sleep sessions)
├── sleep_movement (movement during sleep)
├── sleep_restless_moment (restless periods)
├── spo2 (blood oxygen saturation)
├── hrv (heart rate variability)
└── breathing_disruption (breathing events)
```
*Foreign keys: `sleep` → `user.user_id`; all child tables → `sleep.sleep_id`*

**Health Time-Series (7 tables)**
```
heart_rate (continuous heart rate measurements)
stress (stress level readings)
body_battery (energy level tracking)
respiration (breathing rate data)
steps (step counts and activity levels)
floors (floors climbed/descended)
intensity_minutes (activity intensity tracking)
```
*Foreign keys: all tables → `user.user_id`*

**Training Metrics (4 tables)**
```
vo2_max (VO2 max estimates)
├── acclimation (heat/altitude acclimation)
├── training_load (training load metrics)
└── training_readiness (daily readiness scores)
```
*Foreign keys: all tables → `user.user_id`*

**Records & Predictions (2 tables)**
```
personal_record (personal bests)
race_predictions (predicted race times)
```
*Foreign keys: all tables → `user.user_id`; `personal_record` → `activity.activity_id` (optional)*

**Processing Flow:**

The `process_file_set` method of the custom `GarminProcessor` class orchestrates the processing of all files in a `FileSet`, following a specific sequence to ensure data consistency and referential integrity.

#### 1. User Profile Information ([`_process_user_profile`](process.py#_process_user_profile))

User profile processing is executed first within `process_file_set` to establish the foundational user context required for all subsequent data processing. The method extracts the user ID from filenames and processes any USER_PROFILE files (under normal circumstances only one) to create or update the user's profile record. It ensures a minimal user record exists in the [`garmin.user`](tables.ddl) table before proceeding with USER_PROFILE data processing.

* **JSON file structure**: Root object containing `userData` section with user demographics (gender, weight, height, birth date), preferences (time/measurement formats), and fitness metrics (VO2 max, lactate threshold, HR zones).
* **Target tables**: [`garmin.user`](tables.ddl) for basic user identity and [`garmin.user_profile`](tables.ddl) for detailed fitness metrics.
* **Database method**: Direct SQLAlchemy `session.add()` for `user_profile` table with manual `latest` flag management. User creation uses PostgreSQL `ON CONFLICT` SQL statements. When reprocessing, uses manual `latest` flag management: sets existing `latest=True` records to `latest=False`, then inserts new record with `latest=True`. All profile data updated except user identity.
* **User creation**: Uses `INSERT ... ON CONFLICT (user_id) DO NOTHING` to ensure user record exists in the `garmin.user` table.
* **Latest flag management**: Sets any existing `latest=True` record for same `user_id` to `latest=False`, then inserts new record with `latest=True`.
* **Data processing**: Extracts from `userData` section, processes 11 fields including demographics (full_name, gender, weight, height, birth_date) and fitness metrics (vo2_max_running/cycling, lactate thresholds, HR zones). Uses data as-is with no calculated fields. Uses `.get()` with conditional processing, gender lowercased if present, birthDate parsed to date if present, otherwise None.
* **Data excluded**:
  - All fields outside `userData` section ignored
  - `full_name` fallback from existing record if not in current data
* **Foreign key reference**: All other data tables use `user_id` as the foreign key reference to the `garmin.user` table.

#### 2. JSON Wellness Data Processing

The system processes 13 different JSON data types from [`GARMIN_DATA_REGISTRY`](constants.py) using enum-based routing with specialized functions:

**Activities List Processing** ([`_process_activities`](process.py#_process_activities))
* **JSON file structure**: Array of activity objects containing `activityId`, `activityName`, timestamps (`startTimeLocal`, `startTimeGMT`, `endTimeGMT`), nested objects (`activityType`, `eventType`, `privacy`), activity metrics (distance, duration, calories, heart rate), sport-specific fields (running cadence, power metrics, swimming metrics), and arrays (`userRoles`, `splitSummaries`).
* **Target tables**: [`garmin.activity`](tables.ddl) (main), [`running_agg_metrics`](tables.ddl), [`cycling_agg_metrics`](tables.ddl), [`swimming_agg_metrics`](tables.ddl), [`supplemental_activity_metric`](tables.ddl).
* **Database method**: [`upsert_model_instances`](../../lib/sql_utils.py#upsert_model_instances) for main activity with `["activity_id"]` with `on_conflict_update=True` (update logic); `session.merge()` for sport-specific tables, which uses primary keys for conflict resolution with update logic. When reprocessing, updates all activity data except `activity_id` and `ts_data_available` flag (preserved to maintain FIT file processing state).
* **Data processing**: Uses cascading `pop()` method to remove processed fields, enabling automatic supplemental metrics extraction from remaining fields with sport-specific metrics only processed if sport type matches. Separate processing functions for running, cycling, and swimming metrics with specialized field handling. Supplemental metrics capture all remaining fields not processed by other functions. Calculates `timezone_offset_hours` from local vs GMT time difference, creates timezone-aware `start_ts` and `end_ts` datetime objects, and adds `user_id` foreign key reference.
* **Data excluded**:
  - `userRoles` array containing API scope permissions for security.
  - `privacy` object with activity visibility settings for user privacy.
  - `splitSummaries` array containing detailed split/interval data structures. Detailed split and lap data is acquired via FIT files for each individual activity.
  - Complex nested structures (dictionaries and lists) from supplemental metrics.
  - User profile image URL fields (`ownerProfileImageUrl` variants) for privacy.
  - Non-numeric fields from supplemental metrics (only int, float, bool values stored).
  - Fields with null values from supplemental metrics.

**Sleep Data Processing** ([`_process_sleep`](process.py#_process_sleep))
* **JSON file structure**: Root object containing `dailySleepDTO` with sleep session metadata (sleep duration, window confirmation, timestamps) and five time-series arrays: `sleepMovement`, `restlessEndTimestampGMT`, `spo2Values`, `hrv`, `breathingDisruptions`.
* **Target tables**: [`garmin.sleep`](tables.ddl) (main), [`sleep_movement`](tables.ddl) (hypertable), [`sleep_restless_moment`](tables.ddl) (hypertable), [`spo2`](tables.ddl) (hypertable), [`hrv`](tables.ddl) (hypertable), [`breathing_disruption`](tables.ddl) (hypertable).
* **Database method**: [`upsert_model_instances`](../../lib/sql_utils.py#upsert_model_instances) with dual conflict strategies: main `sleep` table uses `["user_id", "start_ts"]` with `on_conflict_update=True` for session metadata updates, five time-series tables use `["sleep_id", "timestamp"]` with `on_conflict_update=False` for insert-only data.
* **Data processing**: Extracts main sleep record from `dailySleepDTO` and processes 5 time-series arrays using cascading `pop()` operations. Movement (activity_level), restless moments (events), SpO2 (oxygen saturation), HRV (heart rate variability), breathing disruptions, with timestamp validation required (`if timestamp_str`) and empty arrays (`[]`) returning early without processing. Calculates `timezone_offset_hours` from local vs GMT time difference, creates timezone-aware `start_ts` and `end_ts` datetime objects, and adds `user_id` and `sleep_id` foreign key references.
* **Data excluded**: `sleepEndTimestampLocal` explicitly removed, any fields outside the 5 time-series arrays ignored.

**Training Status Processing** ([`_process_training_status`](process.py#_process_training_status))
* **JSON file structure**: Root object containing `mostRecentVO2Max` with nested `generic` and `cycling` VO2 max data including acclimation information, `mostRecentTrainingLoadBalance` with load balance metrics, and `mostRecentTrainingStatus` with ACWR and feedback data.
* **Target tables**: [`garmin.vo2_max`](tables.ddl), [`acclimation`](tables.ddl), [`training_load`](tables.ddl).
* **Database method**: [`upsert_model_instances`](../../lib/sql_utils.py#upsert_model_instances) with `on_conflict_update=True` across three interconnected tables using date-based conflict resolution. `vo2_max` uses `["user_id", "date"]` merging generic/cycling values per record, `acclimation` uses `["user_id", "date", "acclimation_type"]` for heat/altitude differentiation, `training_load` uses `["user_id", "date"]` aggregating balance/ACWR data from this function with intensity minutes data from cross-function processing, requiring `on_conflict_update=True` to merge complementary data fields.
* **Data excluded**: Fields outside the three main sections ignored; missing acclimation data handled gracefully.

**Training Readiness Processing** ([`_process_training_readiness`](process.py#_process_training_readiness))
* **JSON file structure**: Array of readiness objects containing `userProfilePK`, `calendarDate`, `timestamp`, `level` (MODERATE/HIGH/LOW), feedback messages (`feedbackLong`, `feedbackShort`), and associated feature scores.
* **Target table**: [`garmin.training_readiness`](tables.ddl).
* **Database method**: [`upsert_model_instances`](../../lib/sql_utils.py#upsert_model_instances) with `on_conflict_update=True` (update logic) and `["user_id", "timestamp"]` conflict columns. When reprocessing, updates all readiness data except `user_id`, `timestamp`.
* **Data processing**: Extracts daily readiness scores and associated features from JSON array with timestamp parsing and readiness score validation required. Calculates `timezone_offset_hours` from local vs UTC time difference, creates timezone-aware timestamp objects, and adds `user_id` foreign key reference.
* **Data excluded**: Fields outside readiness array ignored.

**Stress and Body Battery Processing** ([`_process_stress_body_battery`](process.py#_process_stress_body_battery))
* **JSON file structure**: Root object containing metadata (user profile, dates, min/max values) and two time-series arrays: `stressValuesArray` with timestamp-stress level pairs and `bodyBatteryValuesArray` with timestamp-battery level pairs.
* **Target tables**: [`garmin.stress`](tables.ddl) (hypertable), [`body_battery`](tables.ddl) (hypertable).
* **Database method**: [`upsert_model_instances`](../../lib/sql_utils.py#upsert_model_instances) with `on_conflict_update=False` (insert-only logic) and `["user_id", "timestamp"]` conflict columns for both tables. When reprocessing, duplicates are ignored, existing data unchanged.
* **Data processing**: Extracts from `stressValuesArray` and `bodyBatteryValuesArray` time-series with timestamp/value tuples. Adds `user_id` foreign key reference to all records.
* **Data excluded**: All fields outside the two time-series arrays ignored.

**Heart Rate Processing** ([`_process_heart_rate`](process.py#_process_heart_rate))
* **JSON file structure**: Root object containing metadata (user profile, dates, resting/min/max heart rates) and `heartRateValues` array with timestamp-heart rate pairs in 2-minute intervals.
* **Target table**: [`garmin.heart_rate`](tables.ddl) (hypertable).
* **Database method**: [`upsert_model_instances`](../../lib/sql_utils.py#upsert_model_instances) with `on_conflict_update=False` (insert-only logic) and `["user_id", "timestamp"]` conflict columns. When reprocessing, duplicates are ignored, existing data unchanged.
* **Data processing**: Extracts from `heartRateValues` array, processes tuples of `[timestamp_ms, heart_rate_value]` requiring both `timestamp_ms` and `heart_rate_value` to be non-null (`if timestamp_ms and heart_rate_value is not None`). Adds `user_id` foreign key reference to all records.
* **Data excluded**: All fields outside `heartRateValues` array ignored.

**Steps Processing** ([`_process_steps`](process.py#_process_steps))
* **JSON file structure**: Array of step interval objects containing `startGMT`, `endGMT`, `steps` count, `pushes` count, and activity level classification (`primaryActivityLevel`).
* **Target table**: [`garmin.steps`](tables.ddl) (hypertable).
* **Database method**: [`upsert_model_instances`](../../lib/sql_utils.py#upsert_model_instances) with `on_conflict_update=False` (insert-only logic) and `["user_id", "timestamp"]` conflict columns. When reprocessing, duplicates are ignored, existing data unchanged.
* **Data processing**: Extracts from `summaryDTO` section, processes 15-minute intervals with step counts and activity levels. Creates timezone-aware timestamp objects from `endGMT` and adds `user_id` foreign key reference.
* **Data excluded**: All fields outside `summaryDTO` section ignored.

**Respiration Processing** ([`_process_respiration`](process.py#_process_respiration))
* **JSON file structure**: Root object containing metadata (user profile, dates, sleep periods) and `respirationValues` array with breathing rate measurements in 2-minute intervals.
* **Target table**: [`garmin.respiration`](tables.ddl) (hypertable).
* **Database method**: [`upsert_model_instances`](../../lib/sql_utils.py#upsert_model_instances) with `on_conflict_update=False` (insert-only logic) and `["user_id", "timestamp"]` conflict columns. When reprocessing, duplicates are ignored, existing data unchanged.
* **Data processing**: Extracts from `respirationValues` time-series array with 2-minute interval measurements. Adds `user_id` foreign key reference to all records.
* **Data excluded**: Aggregated statistics and fields outside time-series array ignored.

**Intensity Minutes Processing** ([`_process_intensity_minutes`](process.py#_process_intensity_minutes))
* **JSON file structure**: Root object containing weekly/daily aggregate metrics (moderate/vigorous minutes, goals) and `wellnessIntensityDtoList` array with time-series intensity data.
* **Target tables**: [`garmin.intensity_minutes`](tables.ddl) (hypertable), [`training_load`](tables.ddl).
* **Database method**: [`upsert_model_instances`](../../lib/sql_utils.py#upsert_model_instances) with `on_conflict_update=False` (insert-only logic) for `intensity_minutes` using `["user_id", "timestamp"]` conflict columns, `on_conflict_update=True` (update logic) for `training_load` using `["user_id", "date"]` conflict columns. Multiple functions contribute to `training_load` records (this function contributes intensity minutes data, Training Status processing contributes balance and ACWR data). When reprocessing, intensity minutes duplicates ignored, training load data updated except `user_id`, `date`.
* **Data processing**: Extracts from `wellnessIntensityDtoList` time-series and aggregate intensity data.
* **Dual processing**: Time-series data to intensity_minutes table, aggregate data to training_load table. Adds `user_id` foreign key reference and parses calendar date for training_load records.

**Floors Processing** ([`_process_floors`](process.py#_process_floors))
* **JSON file structure**: Root object containing metadata (timestamps) with `floorsValueDescriptorDTOList` describing array structure and `floorsValuesList` containing 15-minute interval floor ascent/descent data.
* **Target table**: [`garmin.floors`](tables.ddl) (hypertable).
* **Database method**: [`upsert_model_instances`](../../lib/sql_utils.py#upsert_model_instances) with `on_conflict_update=False` (insert-only logic) and `["user_id", "timestamp"]` conflict columns. When reprocessing, duplicates are ignored, existing data unchanged.
* **Data processing**: Extracts floors ascended/descended from 15-minute interval time-series arrays. Creates timezone-aware timestamp objects from `endTimeGMT` and adds `user_id` foreign key reference.
* **Data excluded**: Aggregate floor counts and non time-series fields ignored.

**Personal Records Processing** ([`_process_personal_records`](process.py#_process_personal_records))
* **JSON file structure**: Array of personal record objects containing `typeId`, `value`, activity information (`activityId`, `activityName`, `activityType`), and timestamps for achievement dates.
* **Target table**: [`garmin.personal_record`](tables.ddl).
* **Database method**: Manual `latest` flag management followed by [`upsert_model_instances`](../../lib/sql_utils.py#upsert_model_instances) with `on_conflict_update=True` and `["user_id", "type_id", "timestamp"]` conflict columns. Sets existing `latest=True` records to `latest=False` for same `user_id` and `type_id`, then upserts new records with `latest=True`. When reprocessing, duplicate `user_id`, `type_id`, `timestamp` combinations are updated, ensuring `latest=True` flag is properly maintained.
* **Data processing**: Extracts personal achievement records using [`PR_TYPE_LABELS`](constants.py#PR_TYPE_LABELS) mapping for record validation. Creates timezone-aware timestamp objects from `prStartTimeGmt` milliseconds and adds `user_id` foreign key reference. Type IDs 12-16 (steps-based records) use `activity_id=NULL` as they represent daily/weekly/monthly aggregates not tied to specific activities. Activity-based records validate `activity_id` existence to prevent foreign key violations, skipping records for missing activities during backfilling.
* **Data excluded**: Records with `typeId` not in PR_TYPE_LABELS mapping, records referencing non-existent activities (with warning logged for backfilling scenarios).

**Race Predictions Processing** ([`_process_race_predictions`](process.py#_process_race_predictions))
* **JSON file structure**: Root object containing `userId`, `calendarDate`, and predicted race times in seconds (`time5K`, `time10K`, `timeHalfMarathon`, `timeMarathon`).
* **Target table**: [`garmin.race_predictions`](tables.ddl).
* **Database method**: [`upsert_model_instances`](../../lib/sql_utils.py#upsert_model_instances) with `on_conflict_update=False` (insert-only logic) and `["user_id", "date"]` conflict columns. When reprocessing, duplicates are ignored, existing predictions unchanged.
* **Data processing**: Extracts predicted race times (5K, 10K, half marathon, marathon) based on current fitness level. Parses calendar date and adds `user_id` foreign key reference.
* **Latest flag management**: Sets previous predictions for same user to `latest=False` before inserting new predictions.
* **Data excluded**: Fields outside race prediction data structure ignored.

#### 3. FIT Activity File Processing ([`_process_fit_file`](process.py#_process_fit_file))

FIT file processing occurs after JSON wellness data processing and handles detailed time-series activity data. Each activity present in the Activities List JSON file should have a corresponding FIT file containing granular sensor measurements, lap metrics, and split data. FIT files provide the detailed temporal data that complements the aggregate metrics already stored from the Activities List processing.

* **Target tables**: [`garmin.activity_ts_metric`](tables.ddl) (hypertable), [`activity_lap_metric`](tables.ddl), [`activity_split_metric`](tables.ddl).
* **Database method**: `session.bulk_save_objects()` for time-series efficiency, updates `activity` table `ts_data_available=True` flag. When reprocessing, checks `ts_data_available` flag and skips processing if `True`. No database conflicts occur as already-processed files are detected and skipped entirely.
* **Data processing**: Uses [`fitdecode`](https://pypi.org/project/fitdecode/) library for binary FIT file parsing with frame-based processing. Processes three frame types: Record frames (time-series sensor data with two-pass timestamp processing → `activity_ts_metric`), Lap frames (device-triggered segments with metric extraction → `activity_lap_metric`), Split frames (algorithmic intervals with type classification: rwd_run, rwd_walk, rwd_stand, interval_active → `activity_split_metric`). Handles array fields using suffix indexing (`_1`, `_2`, etc.) for multiple values per timestamp with field name validation (`field.name is not None`), "unknown" field filtering, and null value checking. Includes binary format validation, type conversion error handling (ValueError, TypeError), and graceful degradation for corrupt data.
* **Data excluded**: "Unknown" field names, null values, fields with invalid field names (`field.name is None`), and corrupted binary data that fails parsing.

## Utility Scripts

### Schema Recreation Script ([`recreate_garmin_schema.sh`](utility_scripts/recreate_garmin_schema.sh))

The `recreate_garmin_schema.sh` utility script provides a convenient way to drop and recreate the entire `garmin` schema with all tables and permissions. This is useful during development, testing, or when schema modifications require a clean slate.

**Usage:**
```bash
./utility_scripts/recreate_garmin_schema.sh <airflow_garmin_password>
```

**What it does:**
1. Drops the existing `garmin` schema (if it exists) with CASCADE option
2. Creates a new empty `garmin` schema
3. Executes [`tables.ddl`](tables.ddl) to create all database tables
4. Applies [`iam.sql`](../../iam.sql) with the provided password to set up user permissions

**Prerequisites:**
- PostgreSQL connection to the `lens` database as `postgres` user
- Valid password for the `airflow_garmin` database user
- Accessible `tables.ddl` and `iam.sql` files in their expected locations

**Safety note:** This script performs a destructive operation by dropping the entire schema. All existing data will be permanently lost.

### Store task

The store task uses the standard `store()` function from the [Standard DAG](../../../README.md#standard-dag) pattern with default implementation.