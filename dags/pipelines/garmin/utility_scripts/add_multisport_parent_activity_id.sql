-- Adds garmin.activity.parent_activity_id (self-FK, ON DELETE CASCADE) for multi-sport
-- (duathlon/triathlon) legs, and replaces the plain UNIQUE (user_id, start_ts) index
-- with a PARTIAL unique index that excludes legs (parent_activity_id IS NOT NULL). A
-- leg may legitimately share a start instant with an independently-recorded standalone
-- activity of the same event, so leg rows are exempted; standalone activities and
-- multi_sport parents stay uniquely constrained, preserving the #66/#67 duplicate guard.
--
-- garmin.activity is NOT a TimescaleDB hypertable (only activity_ts_metric and the
-- wellness time-series tables are), so this is a plain transactional ALTER + index swap
-- with no chunk/partitioning constraints.
--
-- Safety: the column is additive (all existing rows get NULL, so they satisfy
-- parent_activity_id IS NULL and remain covered by the unique index). The partial index
-- is a relaxation of the old unqualified unique index over the exact same rows, so it
-- cannot fail on data that already satisfied the old constraint. Idempotent: ADD COLUMN
-- IF NOT EXISTS and CREATE INDEX IF NOT EXISTS make re-runs no-ops. Run once before
-- deploying the multi-sport pipeline code.
--
-- Usage:
--   psql -h <host> -U postgres -d lens -f add_multisport_parent_activity_id.sql

BEGIN;

ALTER TABLE garmin.activity
ADD COLUMN IF NOT EXISTS parent_activity_id BIGINT
REFERENCES garmin.activity (activity_id) ON DELETE CASCADE;

DROP INDEX IF EXISTS garmin.activity_user_id_start_ts_unique_idx;

CREATE UNIQUE INDEX IF NOT EXISTS activity_user_id_start_ts_unique_idx
ON garmin.activity (user_id, start_ts)
WHERE parent_activity_id IS NULL;

CREATE INDEX IF NOT EXISTS activity_parent_activity_id_idx
ON garmin.activity (parent_activity_id);

COMMENT ON COLUMN garmin.activity.parent_activity_id IS
'For a leg of a multi-sport (duathlon/triathlon) activity, the activity_id of the '
'parent multi_sport activity. NULL for standalone activities and the multi_sport '
'parent itself.';

COMMIT;
