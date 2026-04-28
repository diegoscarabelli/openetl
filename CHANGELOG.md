# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- **Garmin strength training data** ([#113](https://github.com/diegoscarabelli/openetl/issues/113), [#114](https://github.com/diegoscarabelli/openetl/pull/114)): First-class support for strength training activities with two new tables and a new API data source.
  - `garmin.strength_exercise`: Per-exercise aggregates (sets, reps, volume, duration, max weight) derived from `summarizedExerciseSets` in the activities list.
  - `garmin.strength_set`: Per-set granular data (set type, duration, reps, weight, ML-classified exercise name/category) from the `/activity-service/activity/{id}/exerciseSets` API endpoint.
  - Extraction automatically fetches exercise sets for `strength_training` and `fitness_equipment` activity types alongside FIT file downloads.
  - Both tables use delete+insert for reprocessing since composite PK components can change.
  - `EXERCISE_SETS` registered as a new data type in `GarminDataRegistry`.

  **Database migration:**

  Run the following SQL against the `lens` database as a superuser (e.g., `postgres`):

  ```sql
  -- 1. Create tables, indexes, and comments.
  -- Execute the strength_exercise and strength_set DDL blocks from:
  --   dags/pipelines/garmin/tables.ddl (lines 2188-2310)
  --
  -- Or run the full DDL file (all CREATE statements use IF NOT EXISTS):
  \i dags/pipelines/garmin/tables.ddl

  -- 2. Grant permissions.
  -- The airflow_garmin user needs INSERT/UPDATE (already granted schema-wide)
  -- plus table-specific DELETE for the delete+insert pattern:
  GRANT DELETE ON garmin.strength_exercise TO airflow_garmin;
  GRANT DELETE ON garmin.strength_set TO airflow_garmin;

  -- 3. Grant read access (if not already covered by default privileges):
  GRANT SELECT ON garmin.strength_exercise TO readers;
  GRANT SELECT ON garmin.strength_set TO readers;
  ```

  Alternatively, re-run the full IAM script (idempotent):
  ```bash
  psql -U postgres -d lens -f dags/iam.sql
  ```

- **Garmin extraction: failure isolation, retries, and ACTIVITIES_LIST disk-read** ([#134](https://github.com/diegoscarabelli/openetl/issues/134)): back-port of the Garmin pipeline hardening from [garmin-health-data#38](https://github.com/diegoscarabelli/garmin-health-data/pull/38). The Garmin extract task now isolates failures at three levels (per-date, per-data-type, per-activity), retries transient network errors with exponential backoff (2s → 8s → 30s, 4 attempts), and reads the saved `ACTIVITIES_LIST` JSON from `ingest/` instead of re-calling `get_activities_by_date` for every multi-day extract.
  - `_with_retries(fn, *args, **kwargs)` helper wraps every Garmin API call (per-day data, NO_DATE types, activity-list fetch, activity download, exercise-sets fetch) for transient-error absorption.
  - Per-date isolation in `_extract_day_by_day` (renamed from `_process_day_by_day`): one failed day no longer aborts the rest of the date range.
  - Per-data-type isolation in `extract_garmin_data`: one failed type no longer aborts the rest of the account.
  - Per-activity isolation in `extract_fit_activities`: any exception on one activity download is logged with the activity ID; the loop continues. The `get_activities_by_date` call is wrapped so a list-fetch failure records an `ACTIVITIES_LIST` failure cleanly instead of silently producing zero activities.
  - `_load_activities_list_from_disk()` reads and merges per-day `ACTIVITIES_LIST_<date>.json` files within the extractor's `[start_date, end_date]` window, deduping by `activityId` and dropping entries without one. Stale leftover files outside the window are skipped so they never trigger out-of-window FIT downloads. Falls back to a live API call if any file is unreadable OR if the on-disk files don't cover every day in the window (a partial extract that recorded per-day failures would otherwise silently make the FIT-download loop skip activities for the missing days).
  - End-of-task summary lists every per-data-type / per-date / per-activity failure grouped by account first then by data type (capped at 5 per type), so multi-account runs can attribute every gap to the right user. The summary is logged BEFORE the no-files `AirflowSkipException` so a "no files extracted, but per-day failures recorded" run still surfaces what went wrong.
  - `ExtractionFailure` carries the extractor's `user_id`, populated automatically at every append site.

### Fixed

- **`UNIQUE constraint failed: activity_ts_metric` on FIT files with sub-second sampling** (back-port of [garmin-health-data#36](https://github.com/diegoscarabelli/garmin-health-data/issues/36)): the FIT record-frame parser now reads the optional `fractional_timestamp` field paired with `timestamp` and combines them, so high-frequency devices (e.g. Fenix 7 at 2Hz smart-recording) get distinct rows per sub-second sample. Belt-and-suspenders dedup-by-(timestamp, name) before `session.add_all` handles legacy FIT files without `fractional_timestamp`, with a warning that names the activity_id and source filename.
- **Makefile `format` target accepts docformatter exit code 3**: `docformatter --in-place` exits 3 to signal "files modified"; the `format` target now treats exit 3 as non-fatal so the pre-commit hook passes on the first run after editing any docstring. Exit 1 (real docformatter errors like parse failures) continues to fail the target as intended.
