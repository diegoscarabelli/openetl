/*
========================================================================================
TIMESCALEDB RESOURCES FOR GARMIN DATA
========================================================================================
Description: This script creates TimescaleDB hypertables and configures
             compression policies for Garmin Connect timeseries data tables.
========================================================================================
*/

----------------------------------------------------------------------------------------
-- Sleep Movement: 1-minute movement activity levels during sleep sessions
----------------------------------------------------------------------------------------

SELECT create_hypertable(
    'garmin.sleep_movement'
    , by_range('timestamp', INTERVAL '7 days')
);

ALTER TABLE garmin.sleep_movement SET (
    timescaledb.compress
    , timescaledb.compress_segmentby = 'sleep_id'
--    , timescaledb.compress_orderby = 'sleep_id DESC'
);

ALTER TABLE garmin.sleep_movement SET (
    autovacuum_vacuum_scale_factor = 0.02
    , autovacuum_analyze_scale_factor = 0.02
);

SELECT add_compression_policy('garmin.sleep_movement', INTERVAL '30 days');

----------------------------------------------------------------------------------------
-- Sleep Restless Moments: Event-based restless moments during sleep sessions
----------------------------------------------------------------------------------------

SELECT create_hypertable(
    'garmin.sleep_restless_moment'
    , by_range('timestamp', INTERVAL '7 days')
);

ALTER TABLE garmin.sleep_restless_moment SET (
    timescaledb.compress
    , timescaledb.compress_segmentby = 'sleep_id'
--    , timescaledb.compress_orderby = 'sleep_id DESC'
);

ALTER TABLE garmin.sleep_restless_moment SET (
    autovacuum_vacuum_scale_factor = 0.02
    , autovacuum_analyze_scale_factor = 0.02
);

SELECT add_compression_policy(
    'garmin.sleep_restless_moment'
    , INTERVAL '30 days'
);

----------------------------------------------------------------------------------------
-- SpO2: 1-minute blood oxygen saturation measurements during sleep
----------------------------------------------------------------------------------------

SELECT create_hypertable('garmin.spo2', by_range('timestamp', INTERVAL '7 days'));

ALTER TABLE garmin.spo2 SET (
    timescaledb.compress
    , timescaledb.compress_segmentby = 'sleep_id'
--    , timescaledb.compress_orderby = 'sleep_id DESC'
);

ALTER TABLE garmin.spo2 SET (
    autovacuum_vacuum_scale_factor = 0.02
    , autovacuum_analyze_scale_factor = 0.02
);

SELECT add_compression_policy('garmin.spo2', INTERVAL '30 days');

----------------------------------------------------------------------------------------
-- HRV: 5-minute heart rate variability measurements during sleep
----------------------------------------------------------------------------------------

SELECT create_hypertable('garmin.hrv', by_range('timestamp', INTERVAL '7 days'));

ALTER TABLE garmin.hrv SET (
    timescaledb.compress
    , timescaledb.compress_segmentby = 'sleep_id'
--    , timescaledb.compress_orderby = 'sleep_id DESC'
);

ALTER TABLE garmin.hrv SET (
    autovacuum_vacuum_scale_factor = 0.02
    , autovacuum_analyze_scale_factor = 0.02
);

SELECT add_compression_policy('garmin.hrv', INTERVAL '30 days');

----------------------------------------------------------------------------------------
-- Breathing Disruption: Event-based breathing disruption events during sleep
----------------------------------------------------------------------------------------

SELECT create_hypertable(
    'garmin.breathing_disruption'
    , by_range('timestamp', INTERVAL '7 days')
);

ALTER TABLE garmin.breathing_disruption SET (
    timescaledb.compress
    , timescaledb.compress_segmentby = 'sleep_id'
--    , timescaledb.compress_orderby = 'sleep_id DESC'
);

ALTER TABLE garmin.breathing_disruption SET (
    autovacuum_vacuum_scale_factor = 0.02
    , autovacuum_analyze_scale_factor = 0.02
);

SELECT add_compression_policy(
    'garmin.breathing_disruption'
    , INTERVAL '30 days'
);

----------------------------------------------------------------------------------------
-- Body Battery: 3-minute body battery energy level measurements
----------------------------------------------------------------------------------------

SELECT create_hypertable(
    'garmin.body_battery'
    , by_range('timestamp', INTERVAL '7 days')
);

ALTER TABLE garmin.body_battery SET (
    timescaledb.compress
    , timescaledb.compress_segmentby = 'user_id'
--    , timescaledb.compress_orderby = 'user_profile_id DESC'
);

ALTER TABLE garmin.body_battery SET (
    autovacuum_vacuum_scale_factor = 0.02
    , autovacuum_analyze_scale_factor = 0.02
);

SELECT add_compression_policy('garmin.body_battery', INTERVAL '30 days');

----------------------------------------------------------------------------------------
-- Stress: 3-minute stress level measurements
----------------------------------------------------------------------------------------

SELECT create_hypertable('garmin.stress', by_range('timestamp', INTERVAL '7 days'));

ALTER TABLE garmin.stress SET (
    timescaledb.compress
    , timescaledb.compress_segmentby = 'user_id'
--    , timescaledb.compress_orderby = 'user_profile_id DESC'
);

ALTER TABLE garmin.stress SET (
    autovacuum_vacuum_scale_factor = 0.02
    , autovacuum_analyze_scale_factor = 0.02
);

SELECT add_compression_policy('garmin.stress', INTERVAL '30 days');

----------------------------------------------------------------------------------------
-- Heart Rate: 2-minute heart rate measurements
----------------------------------------------------------------------------------------

SELECT create_hypertable('garmin.heart_rate', by_range('timestamp', INTERVAL '7 days'));

ALTER TABLE garmin.heart_rate SET (
    timescaledb.compress
    , timescaledb.compress_segmentby = 'user_id'
--    , timescaledb.compress_orderby = 'user_profile_id DESC'
);

ALTER TABLE garmin.heart_rate SET (
    autovacuum_vacuum_scale_factor = 0.02
    , autovacuum_analyze_scale_factor = 0.02
);

SELECT add_compression_policy('garmin.heart_rate', INTERVAL '30 days');

----------------------------------------------------------------------------------------
-- Steps: 15-minute step count measurements
----------------------------------------------------------------------------------------

SELECT create_hypertable('garmin.steps', by_range('timestamp', INTERVAL '7 days'));

ALTER TABLE garmin.steps SET (
    timescaledb.compress
    , timescaledb.compress_segmentby = 'user_id'
--    , timescaledb.compress_orderby = 'user_profile_id DESC'
);

ALTER TABLE garmin.steps SET (
    autovacuum_vacuum_scale_factor = 0.02
    , autovacuum_analyze_scale_factor = 0.02
);

SELECT add_compression_policy('garmin.steps', INTERVAL '30 days');

----------------------------------------------------------------------------------------
-- Respiration: 2-minute respiration rate measurements
----------------------------------------------------------------------------------------

SELECT create_hypertable('garmin.respiration', by_range('timestamp', INTERVAL '7 days'));

ALTER TABLE garmin.respiration SET (
    timescaledb.compress
    , timescaledb.compress_segmentby = 'user_id'
--    , timescaledb.compress_orderby = 'user_profile_id DESC'
);

ALTER TABLE garmin.respiration SET (
    autovacuum_vacuum_scale_factor = 0.02
    , autovacuum_analyze_scale_factor = 0.02
);

SELECT add_compression_policy('garmin.respiration', INTERVAL '30 days');

----------------------------------------------------------------------------------------
-- Intensity Minutes: 15-minute intensity minute measurements
----------------------------------------------------------------------------------------

SELECT create_hypertable('garmin.intensity_minutes', by_range('timestamp', INTERVAL '7 days'));

ALTER TABLE garmin.intensity_minutes SET (
    timescaledb.compress
    , timescaledb.compress_segmentby = 'user_id'
--    , timescaledb.compress_orderby = 'user_profile_id DESC'
);

ALTER TABLE garmin.intensity_minutes SET (
    autovacuum_vacuum_scale_factor = 0.02
    , autovacuum_analyze_scale_factor = 0.02
);

SELECT add_compression_policy('garmin.intensity_minutes', INTERVAL '30 days');

----------------------------------------------------------------------------------------
-- Floors: 15-minute floors ascended and descended measurements
----------------------------------------------------------------------------------------

SELECT create_hypertable('garmin.floors', by_range('timestamp', INTERVAL '7 days'));

ALTER TABLE garmin.floors SET (
    timescaledb.compress
    , timescaledb.compress_segmentby = 'user_id'
--    , timescaledb.compress_orderby = 'user_profile_id DESC'
);

ALTER TABLE garmin.floors SET (
    autovacuum_vacuum_scale_factor = 0.02
    , autovacuum_analyze_scale_factor = 0.02
);

SELECT add_compression_policy('garmin.floors', INTERVAL '30 days');

----------------------------------------------------------------------------------------
-- Activity TS Metric: Time-series metrics from activity FIT files
----------------------------------------------------------------------------------------

SELECT create_hypertable(
    'garmin.activity_ts_metric'
    , by_range('timestamp', INTERVAL '7 days')
);

ALTER TABLE garmin.activity_ts_metric SET (
    timescaledb.compress
    , timescaledb.compress_segmentby = 'activity_id'
    , timescaledb.compress_orderby = 'name ASC'
);

ALTER TABLE garmin.activity_ts_metric SET (
    autovacuum_vacuum_scale_factor = 0.02
    , autovacuum_analyze_scale_factor = 0.02
);

SELECT add_compression_policy('garmin.activity_ts_metric', INTERVAL '30 days');

----------------------------------------------------------------------------------------
