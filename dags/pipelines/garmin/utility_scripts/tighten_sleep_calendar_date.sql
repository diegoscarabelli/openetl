-- ----------------------------------------------------------------------------------------
-- Tighten garmin.sleep.calendar_date schema.
--
-- Converts calendar_date from TEXT to DATE, makes it NOT NULL, and adds a unique
-- index on (user_id, calendar_date) so each user's calendar date maps to exactly one
-- sleep session. Required prerequisite for the sleep_level table backfill.
--
-- Safety: empirically verified on production (5051 rows): zero NULLs, every value
-- parses as DATE, and (user_id, calendar_date) is already unique. Run this once
-- before deploying the sleep_level feature.
--
-- Usage:
--   psql -h <host> -U postgres -d lens -f tighten_sleep_calendar_date.sql
-- ----------------------------------------------------------------------------------------

BEGIN;

-- Convert TEXT to DATE in place. Fails fast if any row contains a non-parseable
-- value, which is the desired behavior since we are tightening the contract.
ALTER TABLE garmin.sleep
ALTER COLUMN calendar_date TYPE DATE
USING calendar_date::DATE;

-- Enforce non-null. Fails fast if any row has a NULL calendar_date.
ALTER TABLE garmin.sleep
ALTER COLUMN calendar_date SET NOT NULL;

-- Add unique index alongside the existing (user_id, start_ts) unique index.
CREATE UNIQUE INDEX IF NOT EXISTS sleep_user_id_calendar_date_unique_idx
ON garmin.sleep (user_id, calendar_date);

-- Refresh the column comment to reflect the new contract.
COMMENT ON COLUMN garmin.sleep.calendar_date IS
'Calendar date assigned to the sleep session by Garmin Connect. Sourced from '
'dailySleepDTO.calendarDate. Together with user_id forms a unique constraint.';

COMMIT;
