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
