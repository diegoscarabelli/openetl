/*
========================================================================================
SQL RESOURCES FOR GARMIN DATA
========================================================================================
Description: This script creates database tables and other SQL resources for storing
             and analyzing Garmin Connect wellness and activity data.
========================================================================================
*/


----------------------------------------------------------------------------------------

-- User table containing user identity and basic demographics.
CREATE TABLE IF NOT EXISTS garmin.user (
    -- User identification.
    user_id BIGINT PRIMARY KEY

    -- Demographics.
    , full_name TEXT
    , birth_date DATE

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for user table.
CREATE INDEX IF NOT EXISTS user_full_name_idx
ON garmin.user (full_name);
CREATE INDEX IF NOT EXISTS user_create_ts_brin_idx
ON garmin.user USING brin (create_ts);

-- Table comment.
COMMENT ON TABLE garmin.user IS
'User identity and basic demographic data from Garmin Connect. Contains '
'stable user identification and basic profile information.';

-- Column comments.
COMMENT ON COLUMN garmin.user.user_id IS
'Unique identifier for the user in Garmin Connect.';
COMMENT ON COLUMN garmin.user.full_name IS
'Full name of the user.';
COMMENT ON COLUMN garmin.user.birth_date IS
'User birth date.';
COMMENT ON COLUMN garmin.user.create_ts IS
'Timestamp when the record was created in the database.';

----------------------------------------------------------------------------------------

-- User profile table containing fitness metrics and physical characteristics.
CREATE TABLE IF NOT EXISTS garmin.user_profile (
    -- Record identification.
    user_profile_id SERIAL PRIMARY KEY
    , user_id BIGINT NOT NULL REFERENCES garmin.user (user_id)

    -- Physical characteristics.
    , gender TEXT
    , weight FLOAT
    , height FLOAT

    -- Fitness metrics.
    , vo2_max_running FLOAT
    , vo2_max_cycling FLOAT
    , lactate_threshold_speed FLOAT
    , lactate_threshold_heart_rate INTEGER
    , moderate_intensity_minutes_hr_zone INTEGER
    , vigorous_intensity_minutes_hr_zone INTEGER

    -- Record management.
    , latest BOOLEAN NOT NULL DEFAULT FALSE

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS user_profile_user_id_latest_unique_idx
ON garmin.user_profile (user_id) WHERE latest = TRUE;
CREATE INDEX IF NOT EXISTS user_profile_user_id_idx
ON garmin.user_profile (user_id);
CREATE INDEX IF NOT EXISTS user_profile_gender_idx
ON garmin.user_profile (gender);
CREATE INDEX IF NOT EXISTS user_profile_latest_idx
ON garmin.user_profile (latest);
CREATE INDEX IF NOT EXISTS user_profile_create_ts_brin_idx
ON garmin.user_profile USING brin (create_ts);

-- Table comment.
COMMENT ON TABLE garmin.user_profile IS
'User fitness profile data from Garmin Connect including physical '
'characteristics and fitness metrics. The latest column indicates the '
'most recent profile record.';

-- Column comments.
COMMENT ON COLUMN garmin.user_profile.user_id IS
'Auto-incrementing primary key for user profile records.';
COMMENT ON COLUMN garmin.user_profile.user_id IS
'References garmin.user(user_id). Identifies which user this profile '
'record belongs to.';
COMMENT ON COLUMN garmin.user_profile.gender IS
'User gender (e.g., ''MALE'', ''FEMALE'').';
COMMENT ON COLUMN garmin.user_profile.weight IS
'User weight in grams.';
COMMENT ON COLUMN garmin.user_profile.height IS
'User height in centimeters.';
COMMENT ON COLUMN garmin.user_profile.vo2_max_running IS
'VO2 max value for running activities in ml/kg/min.';
COMMENT ON COLUMN garmin.user_profile.vo2_max_cycling IS
'VO2 max value for cycling activities in ml/kg/min.';
COMMENT ON COLUMN garmin.user_profile.lactate_threshold_speed IS
'Lactate threshold speed in meters per second.';
COMMENT ON COLUMN garmin.user_profile.lactate_threshold_heart_rate IS
'Lactate threshold heart rate in beats per minute.';
COMMENT ON COLUMN garmin.user_profile.moderate_intensity_minutes_hr_zone IS
'Heart rate zone for moderate intensity exercise minutes.';
COMMENT ON COLUMN garmin.user_profile.vigorous_intensity_minutes_hr_zone IS
'Heart rate zone for vigorous intensity exercise minutes.';
COMMENT ON COLUMN garmin.user_profile.latest IS
'Boolean flag indicating whether this is the latest user profile record.';
COMMENT ON COLUMN garmin.user_profile.create_ts IS
'Timestamp when the record was created in the database.';

----------------------------------------------------------------------------------------

-- Main activity table containing core metrics common across all activity types.
CREATE TABLE IF NOT EXISTS garmin.activity (
    -- Activity identification.
    activity_id BIGINT PRIMARY KEY
    , user_id BIGINT NOT NULL REFERENCES garmin.user (user_id)
    , activity_name TEXT
    , activity_type_id INTEGER NOT NULL
    , activity_type_key TEXT NOT NULL
    , event_type_id INTEGER NOT NULL
    , event_type_key TEXT NOT NULL

    -- Time.
    , start_ts TIMESTAMPTZ NOT NULL
    , end_ts TIMESTAMPTZ NOT NULL
    , timezone_offset_hours FLOAT NOT NULL
    , duration FLOAT
    , elapsed_duration FLOAT
    , moving_duration FLOAT

    -- Distance, speed, laps.
    , distance FLOAT
    , lap_count INTEGER
    , average_speed FLOAT
    , max_speed FLOAT

    -- Location.
    , start_latitude FLOAT
    , start_longitude FLOAT
    , end_latitude FLOAT
    , end_longitude FLOAT
    , location_name TEXT

    -- Training effect and load.
    , aerobic_training_effect FLOAT
    , aerobic_training_effect_message TEXT
    , anaerobic_training_effect FLOAT
    , anaerobic_training_effect_message TEXT
    , training_effect_label TEXT
    , activity_training_load FLOAT
    , difference_body_battery INTEGER
    , moderate_intensity_minutes INTEGER
    , vigorous_intensity_minutes INTEGER

    -- Metabolism.
    , calories FLOAT
    , bmr_calories FLOAT
    , water_estimated FLOAT

    -- Heart rate zones.
    , hr_time_in_zone_1 FLOAT
    , hr_time_in_zone_2 FLOAT
    , hr_time_in_zone_3 FLOAT
    , hr_time_in_zone_4 FLOAT
    , hr_time_in_zone_5 FLOAT
    , average_hr FLOAT
    , max_hr FLOAT

    -- Device and technical info.
    , device_id BIGINT
    , manufacturer TEXT
    , time_zone_id INTEGER

    -- Data availability flags.
    , has_polyline BOOLEAN NOT NULL
    , has_images BOOLEAN NOT NULL
    , has_video BOOLEAN NOT NULL
    , has_splits BOOLEAN
    , has_heat_map BOOLEAN NOT NULL
    , ts_data_available BOOLEAN NOT NULL DEFAULT FALSE

    -- Activity status flags.
    , parent BOOLEAN NOT NULL
    , purposeful BOOLEAN NOT NULL
    , favorite BOOLEAN NOT NULL
    , elevation_corrected BOOLEAN
    , atp_activity BOOLEAN
    , manual_activity BOOLEAN NOT NULL
    , pr BOOLEAN NOT NULL
    , auto_calc_calories BOOLEAN NOT NULL

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
    , update_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Create indexes on activity table foreign key and text columns.
CREATE UNIQUE INDEX IF NOT EXISTS activity_user_id_start_ts_unique_idx
ON garmin.activity (user_id, start_ts);
CREATE INDEX IF NOT EXISTS activity_user_id_idx
ON garmin.activity (user_id);
CREATE INDEX IF NOT EXISTS activity_activity_name_idx
ON garmin.activity (activity_name);
CREATE INDEX IF NOT EXISTS activity_activity_type_key_idx
ON garmin.activity (activity_type_key);
CREATE INDEX IF NOT EXISTS activity_event_type_key_idx
ON garmin.activity (event_type_key);
CREATE INDEX IF NOT EXISTS activity_location_name_idx
ON garmin.activity (location_name);
CREATE INDEX IF NOT EXISTS activity_aerobic_training_effect_message_idx
ON garmin.activity (aerobic_training_effect_message);
CREATE INDEX IF NOT EXISTS activity_anaerobic_training_effect_message_idx
ON garmin.activity (anaerobic_training_effect_message);
CREATE INDEX IF NOT EXISTS activity_training_effect_label_idx
ON garmin.activity (training_effect_label);
CREATE INDEX IF NOT EXISTS activity_manufacturer_idx
ON garmin.activity (manufacturer);

-- Create BRIN indexes on activity table timestamp columns.
CREATE INDEX IF NOT EXISTS activity_start_ts_brin_idx
ON garmin.activity USING brin (start_ts);
CREATE INDEX IF NOT EXISTS activity_end_ts_brin_idx
ON garmin.activity USING brin (end_ts);
CREATE INDEX IF NOT EXISTS activity_timezone_offset_hours_idx
ON garmin.activity (timezone_offset_hours);

-- Create indexes on activity table heart rate and training columns.
CREATE INDEX IF NOT EXISTS activity_hr_time_in_zone_1_idx
ON garmin.activity (hr_time_in_zone_1);
CREATE INDEX IF NOT EXISTS activity_hr_time_in_zone_2_idx
ON garmin.activity (hr_time_in_zone_2);
CREATE INDEX IF NOT EXISTS activity_hr_time_in_zone_3_idx
ON garmin.activity (hr_time_in_zone_3);
CREATE INDEX IF NOT EXISTS activity_hr_time_in_zone_4_idx
ON garmin.activity (hr_time_in_zone_4);
CREATE INDEX IF NOT EXISTS activity_hr_time_in_zone_5_idx
ON garmin.activity (hr_time_in_zone_5);
CREATE INDEX IF NOT EXISTS activity_average_hr_idx
ON garmin.activity (average_hr);
CREATE INDEX IF NOT EXISTS activity_max_hr_idx
ON garmin.activity (max_hr);
CREATE INDEX IF NOT EXISTS activity_aerobic_training_effect_idx
ON garmin.activity (aerobic_training_effect);
CREATE INDEX IF NOT EXISTS activity_anaerobic_training_effect_idx
ON garmin.activity (anaerobic_training_effect);
CREATE INDEX IF NOT EXISTS activity_training_load_idx
ON garmin.activity (activity_training_load);
CREATE INDEX IF NOT EXISTS activity_moving_duration_idx
ON garmin.activity (moving_duration);

-- Create indexes on activity table boolean columns.
CREATE INDEX IF NOT EXISTS activity_pr_idx
ON garmin.activity (pr);
CREATE INDEX IF NOT EXISTS activity_has_splits_idx
ON garmin.activity (has_splits);
CREATE INDEX IF NOT EXISTS activity_has_polyline_idx
ON garmin.activity (has_polyline);
CREATE INDEX IF NOT EXISTS activity_ts_data_available_idx
ON garmin.activity (ts_data_available);
CREATE INDEX IF NOT EXISTS activity_parent_idx
ON garmin.activity (parent);

-- Table comment.
COMMENT ON TABLE garmin.activity IS
'Garmin Connect activity records with core metrics common across all '
'activity types.';

-- Column comments.
COMMENT ON COLUMN garmin.activity.activity_id IS
'Unique identifier for the activity in Garmin Connect.';
COMMENT ON COLUMN garmin.activity.user_id IS
'References garmin.user(user_id). Identifies which user performed this activity.';
COMMENT ON COLUMN garmin.activity.activity_name IS
'User-defined name for the activity.';
COMMENT ON COLUMN garmin.activity.activity_type_id IS
'Unique identifier for the activity type (e.g., ''1'' for running, '
'''11'' for cardio).';
COMMENT ON COLUMN garmin.activity.activity_type_key IS
'String key for the activity type (e.g., ''running'', ''lap_swimming'', '
'''road_biking'', ''indoor_cardio'').';
COMMENT ON COLUMN garmin.activity.event_type_id IS
'Unique identifier for the event type.';
COMMENT ON COLUMN garmin.activity.event_type_key IS
'String key for the event type (e.g., ''other'').';
COMMENT ON COLUMN garmin.activity.start_ts IS
'Activity start time.';
COMMENT ON COLUMN garmin.activity.end_ts IS
'Activity end time.';
COMMENT ON COLUMN garmin.activity.timezone_offset_hours IS
'Timezone offset from UTC in hours to infer local time '
'(e.g., -7.0 for UTC-07:00, 5.5 for UTC+05:30).';
COMMENT ON COLUMN garmin.activity.duration IS
'Total duration of the activity in seconds.';
COMMENT ON COLUMN garmin.activity.elapsed_duration IS
'Elapsed time including pauses and stops in seconds.';
COMMENT ON COLUMN garmin.activity.moving_duration IS
'Time spent in motion during the activity in seconds.';
COMMENT ON COLUMN garmin.activity.distance IS
'Total distance covered during the activity in meters.';
COMMENT ON COLUMN garmin.activity.lap_count IS
'Number of laps/segments in the activity.';
COMMENT ON COLUMN garmin.activity.average_speed IS
'Average speed during the activity in meters per second.';
COMMENT ON COLUMN garmin.activity.max_speed IS
'Maximum speed reached during the activity in meters per second.';
COMMENT ON COLUMN garmin.activity.start_latitude IS
'Starting latitude coordinate in decimal degrees.';
COMMENT ON COLUMN garmin.activity.start_longitude IS
'Starting longitude coordinate in decimal degrees.';
COMMENT ON COLUMN garmin.activity.end_latitude IS
'Ending latitude coordinate in decimal degrees.';
COMMENT ON COLUMN garmin.activity.end_longitude IS
'Ending longitude coordinate in decimal degrees.';
COMMENT ON COLUMN garmin.activity.location_name IS
'Geographic location name where the activity took place.';
COMMENT ON COLUMN garmin.activity.aerobic_training_effect IS
'Aerobic training effect score (0.0-5.0 scale).';
COMMENT ON COLUMN garmin.activity.aerobic_training_effect_message IS
'Detailed message about aerobic training effect.';
COMMENT ON COLUMN garmin.activity.anaerobic_training_effect IS
'Anaerobic training effect score (0.0-5.0 scale).';
COMMENT ON COLUMN garmin.activity.anaerobic_training_effect_message IS
'Detailed message about anaerobic training effect.';
COMMENT ON COLUMN garmin.activity.training_effect_label IS
'Text description of the training effect (e.g., ''AEROBIC_BASE'', '
'''UNKNOWN'').';
COMMENT ON COLUMN garmin.activity.activity_training_load IS
'Training load value representing the physiological impact of the '
'activity.';
COMMENT ON COLUMN garmin.activity.difference_body_battery IS
'Change in body battery energy level during the activity.';
COMMENT ON COLUMN garmin.activity.moderate_intensity_minutes IS
'Minutes spent in moderate intensity exercise zone.';
COMMENT ON COLUMN garmin.activity.vigorous_intensity_minutes IS
'Minutes spent in vigorous intensity exercise zone.';
COMMENT ON COLUMN garmin.activity.calories IS
'Total calories burned during the activity.';
COMMENT ON COLUMN garmin.activity.bmr_calories IS
'Basal metabolic rate calories burned during the activity.';
COMMENT ON COLUMN garmin.activity.water_estimated IS
'Estimated water loss during the activity in milliliters.';
COMMENT ON COLUMN garmin.activity.hr_time_in_zone_1 IS
'Time spent in heart rate zone 1 (active recovery) in seconds.';
COMMENT ON COLUMN garmin.activity.hr_time_in_zone_2 IS
'Time spent in heart rate zone 2 (aerobic base) in seconds.';
COMMENT ON COLUMN garmin.activity.hr_time_in_zone_3 IS
'Time spent in heart rate zone 3 (aerobic) in seconds.';
COMMENT ON COLUMN garmin.activity.hr_time_in_zone_4 IS
'Time spent in heart rate zone 4 (lactate threshold) in seconds.';
COMMENT ON COLUMN garmin.activity.hr_time_in_zone_5 IS
'Time spent in heart rate zone 5 (neuromuscular power) in seconds.';
COMMENT ON COLUMN garmin.activity.average_hr IS
'Average heart rate during the activity in beats per minute.';
COMMENT ON COLUMN garmin.activity.max_hr IS
'Maximum heart rate reached during the activity in beats per minute.';
COMMENT ON COLUMN garmin.activity.device_id IS
'Unique identifier for the Garmin device used to record the activity.';
COMMENT ON COLUMN garmin.activity.manufacturer IS
'Manufacturer of the device (typically ''GARMIN'').';
COMMENT ON COLUMN garmin.activity.time_zone_id IS
'Garmin''s internal timezone identifier for the activity location.';
COMMENT ON COLUMN garmin.activity.has_polyline IS
'Whether GPS track data (polyline) is available for this activity.';
COMMENT ON COLUMN garmin.activity.has_images IS
'Whether images are attached to this activity.';
COMMENT ON COLUMN garmin.activity.has_video IS
'Whether video is attached to this activity.';
COMMENT ON COLUMN garmin.activity.has_splits IS
'Whether split/lap data is available for this activity.';
COMMENT ON COLUMN garmin.activity.has_heat_map IS
'Whether heat map data is available for this activity.';
COMMENT ON COLUMN garmin.activity.ts_data_available IS
'Whether time-series data from FIT file has been processed for this activity.';
COMMENT ON COLUMN garmin.activity.parent IS
'Whether this activity is a parent activity containing sub-activities.';
COMMENT ON COLUMN garmin.activity.purposeful IS
'Whether this activity was marked as purposeful training.';
COMMENT ON COLUMN garmin.activity.favorite IS
'Whether this activity is marked as a favorite.';
COMMENT ON COLUMN garmin.activity.elevation_corrected IS
'Whether elevation data has been corrected.';
COMMENT ON COLUMN garmin.activity.atp_activity IS
'Whether this is an Adaptive Training Plan activity.';
COMMENT ON COLUMN garmin.activity.manual_activity IS
'Whether this activity was manually entered rather than recorded.';
COMMENT ON COLUMN garmin.activity.pr IS
'Whether this activity contains a personal record.';
COMMENT ON COLUMN garmin.activity.auto_calc_calories IS
'Whether calorie calculation was performed automatically.';
COMMENT ON COLUMN garmin.activity.create_ts IS
'Timestamp when the record was created in the database.';
COMMENT ON COLUMN garmin.activity.update_ts IS
'Timestamp when the record was last modified in the database.';

----------------------------------------------------------------------------------------

-- Swimming-specific aggregate metrics for pool and open water activities.
CREATE TABLE IF NOT EXISTS garmin.swimming_agg_metrics (
    activity_id BIGINT PRIMARY KEY
    REFERENCES garmin.activity (activity_id) ON DELETE CASCADE
    , pool_length FLOAT
    , active_lengths INTEGER
    , strokes FLOAT
    , avg_stroke_distance FLOAT
    , avg_strokes FLOAT
    , avg_swim_cadence FLOAT
    , avg_swolf FLOAT

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
    , update_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Table comment.
COMMENT ON TABLE garmin.swimming_agg_metrics IS
'Swimming-specific metrics including stroke data, SWOLF, and pool '
'information. Each record corresponds to a specific swimming activity.';

-- Column comments.
COMMENT ON COLUMN garmin.swimming_agg_metrics.activity_id IS
'References garmin.activity(activity_id).';
COMMENT ON COLUMN garmin.swimming_agg_metrics.pool_length IS
'Length of the swimming pool in centimeters.';
COMMENT ON COLUMN garmin.swimming_agg_metrics.active_lengths IS
'Number of active pool lengths swum.';
COMMENT ON COLUMN garmin.swimming_agg_metrics.strokes IS
'Total number of strokes taken during the activity.';
COMMENT ON COLUMN garmin.swimming_agg_metrics.avg_stroke_distance IS
'Average distance covered per stroke in meters.';
COMMENT ON COLUMN garmin.swimming_agg_metrics.avg_strokes IS
'Average number of strokes per pool length.';
COMMENT ON COLUMN garmin.swimming_agg_metrics.avg_swim_cadence IS
'Average swimming cadence in strokes per minute.';
COMMENT ON COLUMN garmin.swimming_agg_metrics.avg_swolf IS
'Average SWOLF score (strokes + time in seconds to cover pool length).';
COMMENT ON COLUMN garmin.swimming_agg_metrics.create_ts IS
'Timestamp when the record was created in the database.';
COMMENT ON COLUMN garmin.swimming_agg_metrics.update_ts IS
'Timestamp when the record was last modified in the database.';

----------------------------------------------------------------------------------------

-- Cycling-specific aggregate metrics including power, cadence, and training data.
CREATE TABLE IF NOT EXISTS garmin.cycling_agg_metrics (
    activity_id BIGINT PRIMARY KEY
    REFERENCES garmin.activity (activity_id) ON DELETE CASCADE
    , training_stress_score FLOAT
    , intensity_factor FLOAT
    , vo2_max_value FLOAT

    -- Power metrics.
    , avg_power FLOAT
    , max_power FLOAT
    , normalized_power FLOAT
    , max_20min_power FLOAT
    , avg_left_balance FLOAT

    -- Cycling cadence.
    , avg_biking_cadence FLOAT
    , max_biking_cadence FLOAT

    -- Power curve - maximum average power over time periods.
    , max_avg_power_1 FLOAT
    , max_avg_power_2 FLOAT
    , max_avg_power_5 FLOAT
    , max_avg_power_10 FLOAT
    , max_avg_power_20 FLOAT
    , max_avg_power_30 FLOAT
    , max_avg_power_60 FLOAT
    , max_avg_power_120 FLOAT
    , max_avg_power_300 FLOAT
    , max_avg_power_600 FLOAT
    , max_avg_power_1200 FLOAT
    , max_avg_power_1800 FLOAT
    , max_avg_power_3600 FLOAT
    , max_avg_power_7200 FLOAT
    , max_avg_power_18000 FLOAT

    -- Power zones - time spent in each power training zone.
    , power_time_in_zone_1 FLOAT
    , power_time_in_zone_2 FLOAT
    , power_time_in_zone_3 FLOAT
    , power_time_in_zone_4 FLOAT
    , power_time_in_zone_5 FLOAT
    , power_time_in_zone_6 FLOAT
    , power_time_in_zone_7 FLOAT

    -- Environmental conditions.
    , min_temperature FLOAT
    , max_temperature FLOAT

    -- Elevation metrics.
    , elevation_gain FLOAT
    , elevation_loss FLOAT
    , min_elevation FLOAT
    , max_elevation FLOAT

    -- Respiration metrics.
    , min_respiration_rate FLOAT
    , max_respiration_rate FLOAT
    , avg_respiration_rate FLOAT

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
    , update_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Table comment.
COMMENT ON TABLE garmin.cycling_agg_metrics IS
'Cycling-specific metrics including power zones, cadence, and '
'performance analysis. Each record corresponds to a specific cycling '
'activity.';

-- Column comments.
COMMENT ON COLUMN garmin.cycling_agg_metrics.activity_id IS
'References garmin.activity(activity_id).';
COMMENT ON COLUMN garmin.cycling_agg_metrics.training_stress_score IS
'Training Stress Score quantifying workout intensity and duration.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.intensity_factor IS
'Intensity Factor representing workout intensity relative to threshold.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.vo2_max_value IS
'VO2 max value measured during the activity in ml/kg/min.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.avg_power IS
'Average power output during the activity in watts.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.max_power IS
'Maximum power output reached during the activity in watts.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.normalized_power IS
'Normalized power accounting for variable intensity in watts.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.max_20min_power IS
'Best 20-minute average power output in watts.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.avg_left_balance IS
'Average left/right power balance as percentage of left leg '
'contribution.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.avg_biking_cadence IS
'Average pedaling cadence in revolutions per minute.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.max_biking_cadence IS
'Maximum pedaling cadence reached in revolutions per minute.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.max_avg_power_1 IS
'Best 1-second average power in watts.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.max_avg_power_2 IS
'Best 2-second average power in watts.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.max_avg_power_5 IS
'Best 5-second average power in watts.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.max_avg_power_10 IS
'Best 10-second average power in watts.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.max_avg_power_20 IS
'Best 20-second average power in watts.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.max_avg_power_30 IS
'Best 30-second average power in watts.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.max_avg_power_60 IS
'Best 1-minute average power in watts.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.max_avg_power_120 IS
'Best 2-minute average power in watts.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.max_avg_power_300 IS
'Best 5-minute average power in watts.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.max_avg_power_600 IS
'Best 10-minute average power in watts.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.max_avg_power_1200 IS
'Best 20-minute average power in watts.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.max_avg_power_1800 IS
'Best 30-minute average power in watts.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.max_avg_power_3600 IS
'Best 60-minute average power in watts.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.max_avg_power_7200 IS
'Best 120-minute average power in watts.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.max_avg_power_18000 IS
'Best 300-minute average power in watts.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.power_time_in_zone_1 IS
'Time spent in power zone 1 (active recovery) in seconds.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.power_time_in_zone_2 IS
'Time spent in power zone 2 (endurance) in seconds.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.power_time_in_zone_3 IS
'Time spent in power zone 3 (tempo) in seconds.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.power_time_in_zone_4 IS
'Time spent in power zone 4 (lactate threshold) in seconds.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.power_time_in_zone_5 IS
'Time spent in power zone 5 (VO2 max) in seconds.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.power_time_in_zone_6 IS
'Time spent in power zone 6 (anaerobic capacity) in seconds.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.power_time_in_zone_7 IS
'Time spent in power zone 7 (neuromuscular) in seconds.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.min_temperature IS
'Minimum temperature recorded during the activity in Celsius.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.max_temperature IS
'Maximum temperature recorded during the activity in Celsius.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.elevation_gain IS
'Total elevation gained during the activity in meters.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.elevation_loss IS
'Total elevation lost during the activity in meters.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.min_elevation IS
'Minimum elevation during the activity in meters.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.max_elevation IS
'Maximum elevation during the activity in meters.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.min_respiration_rate IS
'Minimum respiration rate during the activity in breaths per minute.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.max_respiration_rate IS
'Maximum respiration rate during the activity in breaths per minute.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.avg_respiration_rate IS
'Average respiration rate during the activity in breaths per minute.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.create_ts IS
'Timestamp when the record was created in the database.';
COMMENT ON COLUMN garmin.cycling_agg_metrics.update_ts IS
'Timestamp when the record was last modified in the database.';

----------------------------------------------------------------------------------------

-- Running-specific aggregate metrics including form, cadence, and performance data.
CREATE TABLE IF NOT EXISTS garmin.running_agg_metrics (
    activity_id BIGINT PRIMARY KEY
    REFERENCES garmin.activity (activity_id) ON DELETE CASCADE
    , steps INTEGER
    , vo2_max_value FLOAT

    -- Running cadence.
    , avg_running_cadence FLOAT
    , max_running_cadence FLOAT
    , max_double_cadence FLOAT

    -- Running form metrics.
    , avg_vertical_oscillation FLOAT
    , avg_ground_contact_time FLOAT
    , avg_stride_length FLOAT
    , avg_vertical_ratio FLOAT
    , avg_ground_contact_balance FLOAT

    -- Power metrics.
    , avg_power FLOAT
    , max_power FLOAT
    , normalized_power FLOAT

    -- Power zones - time spent in each power training zone.
    , power_time_in_zone_1 FLOAT
    , power_time_in_zone_2 FLOAT
    , power_time_in_zone_3 FLOAT
    , power_time_in_zone_4 FLOAT
    , power_time_in_zone_5 FLOAT

    -- Temperature.
    , min_temperature FLOAT
    , max_temperature FLOAT

    -- Elevation metrics.
    , elevation_gain FLOAT
    , elevation_loss FLOAT
    , min_elevation FLOAT
    , max_elevation FLOAT

    -- Respiration metrics.
    , min_respiration_rate FLOAT
    , max_respiration_rate FLOAT
    , avg_respiration_rate FLOAT

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
    , update_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Table comment.
COMMENT ON TABLE garmin.running_agg_metrics IS
'Running-specific metrics including running form, cadence, and split '
'times. Each record corresponds to a specific running activity.';

-- Column comments.
COMMENT ON COLUMN garmin.running_agg_metrics.activity_id IS
'References garmin.activity(activity_id).';
COMMENT ON COLUMN garmin.running_agg_metrics.steps IS
'Total number of steps taken during the running activity.';
COMMENT ON COLUMN garmin.running_agg_metrics.vo2_max_value IS
'VO2 max value measured during the activity in ml/kg/min.';
COMMENT ON COLUMN garmin.running_agg_metrics.avg_running_cadence IS
'Average running cadence in steps per minute.';
COMMENT ON COLUMN garmin.running_agg_metrics.max_running_cadence IS
'Maximum running cadence reached in steps per minute.';
COMMENT ON COLUMN garmin.running_agg_metrics.max_double_cadence IS
'Maximum double cadence (both feet) in steps per minute.';
COMMENT ON COLUMN garmin.running_agg_metrics.avg_vertical_oscillation IS
'Average vertical oscillation of running form in centimeters.';
COMMENT ON COLUMN garmin.running_agg_metrics.avg_ground_contact_time IS
'Average ground contact time per step in milliseconds.';
COMMENT ON COLUMN garmin.running_agg_metrics.avg_stride_length IS
'Average stride length in centimeters.';
COMMENT ON COLUMN garmin.running_agg_metrics.avg_vertical_ratio IS
'Average vertical ratio as percentage of stride length.';
COMMENT ON COLUMN garmin.running_agg_metrics.avg_ground_contact_balance IS
'Average left/right ground contact time balance as percentage.';
COMMENT ON COLUMN garmin.running_agg_metrics.avg_power IS
'Average power output during the activity in watts.';
COMMENT ON COLUMN garmin.running_agg_metrics.max_power IS
'Maximum power output reached during the activity in watts.';
COMMENT ON COLUMN garmin.running_agg_metrics.normalized_power IS
'Normalized power accounting for variable intensity in watts.';
COMMENT ON COLUMN garmin.running_agg_metrics.power_time_in_zone_1 IS
'Time spent in power zone 1 (active recovery) in seconds.';
COMMENT ON COLUMN garmin.running_agg_metrics.power_time_in_zone_2 IS
'Time spent in power zone 2 (endurance) in seconds.';
COMMENT ON COLUMN garmin.running_agg_metrics.power_time_in_zone_3 IS
'Time spent in power zone 3 (tempo) in seconds.';
COMMENT ON COLUMN garmin.running_agg_metrics.power_time_in_zone_4 IS
'Time spent in power zone 4 (lactate threshold) in seconds.';
COMMENT ON COLUMN garmin.running_agg_metrics.power_time_in_zone_5 IS
'Time spent in power zone 5 (VO2 max) in seconds.';
COMMENT ON COLUMN garmin.running_agg_metrics.min_temperature IS
'Minimum temperature recorded during the activity in Celsius.';
COMMENT ON COLUMN garmin.running_agg_metrics.max_temperature IS
'Maximum temperature recorded during the activity in Celsius.';
COMMENT ON COLUMN garmin.running_agg_metrics.elevation_gain IS
'Total elevation gained during the activity in meters.';
COMMENT ON COLUMN garmin.running_agg_metrics.elevation_loss IS
'Total elevation lost during the activity in meters.';
COMMENT ON COLUMN garmin.running_agg_metrics.min_elevation IS
'Minimum elevation during the activity in meters.';
COMMENT ON COLUMN garmin.running_agg_metrics.max_elevation IS
'Maximum elevation during the activity in meters.';
COMMENT ON COLUMN garmin.running_agg_metrics.min_respiration_rate IS
'Minimum respiration rate during the activity in breaths per minute.';
COMMENT ON COLUMN garmin.running_agg_metrics.max_respiration_rate IS
'Maximum respiration rate during the activity in breaths per minute.';
COMMENT ON COLUMN garmin.running_agg_metrics.avg_respiration_rate IS
'Average respiration rate during the activity in breaths per minute.';
COMMENT ON COLUMN garmin.running_agg_metrics.create_ts IS
'Timestamp when the record was created in the database.';
COMMENT ON COLUMN garmin.running_agg_metrics.update_ts IS
'Timestamp when the record was last modified in the database.';

----------------------------------------------------------------------------------------

-- Long table for storing miscellaneous activity metrics.
CREATE TABLE IF NOT EXISTS garmin.supplemental_activity_metric (
    activity_id BIGINT
    REFERENCES garmin.activity (activity_id) ON DELETE CASCADE
    , metric TEXT
    , value FLOAT

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
    , update_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()

    -- Composite primary key.
    , PRIMARY KEY (activity_id, metric)
);

CREATE INDEX IF NOT EXISTS supplemental_activity_metric_metric_idx
ON garmin.supplemental_activity_metric (metric);
CREATE INDEX IF NOT EXISTS supplemental_activity_metric_value_idx
ON garmin.supplemental_activity_metric (value);

-- Table comment.
COMMENT ON TABLE garmin.supplemental_activity_metric IS
'Supplemental activity metrics with flexible key-value storage. '
'Allows for additional metrics not captured in the main tables.';

-- Column comments.
COMMENT ON COLUMN garmin.supplemental_activity_metric.activity_id IS
'References garmin.activity(activity_id).';
COMMENT ON COLUMN garmin.supplemental_activity_metric.metric IS
'Name of the metric being stored.';
COMMENT ON COLUMN garmin.supplemental_activity_metric.value IS
'Numeric value of the metric.';
COMMENT ON COLUMN garmin.supplemental_activity_metric.create_ts IS
'Timestamp when the record was created in the database.';
COMMENT ON COLUMN garmin.supplemental_activity_metric.update_ts IS
'Timestamp when the record was last modified in the database.';

----------------------------------------------------------------------------------------

-- Sleep session data with comprehensive sleep analysis metrics.
CREATE TABLE IF NOT EXISTS garmin.sleep (
    -- Auto-generated primary key.
    sleep_id SERIAL PRIMARY KEY

    -- Foreign key reference.
    , user_id BIGINT NOT NULL REFERENCES garmin.user (user_id)

    -- Non-nullable timestamps.
    , start_ts TIMESTAMPTZ NOT NULL
    , end_ts TIMESTAMPTZ NOT NULL
    , timezone_offset_hours FLOAT NOT NULL

    -- Sleep session metadata.
    , calendar_date TEXT
    , sleep_version INTEGER
    , age_group TEXT
    , respiration_version INTEGER

    -- Sleep duration and stages.
    , sleep_time_seconds INTEGER
    , nap_time_seconds INTEGER
    , unmeasurable_sleep_seconds INTEGER
    , deep_sleep_seconds INTEGER
    , light_sleep_seconds INTEGER
    , rem_sleep_seconds INTEGER
    , awake_sleep_seconds INTEGER
    , awake_count INTEGER
    , restless_moments_count INTEGER
    , rem_sleep_data BOOLEAN

    -- Sleep window and detection.
    , sleep_window_confirmed BOOLEAN
    , sleep_window_confirmation_type TEXT
    , sleep_quality_type_pk BIGINT
    , sleep_result_type_pk BIGINT
    , retro BOOLEAN
    , sleep_from_device BOOLEAN
    , device_rem_capable BOOLEAN
    , skin_temp_data_exists BOOLEAN

    -- Physiological metrics.
    , average_spo2 FLOAT
    , lowest_spo2 INTEGER
    , highest_spo2 INTEGER
    , average_spo2_hr_sleep FLOAT
    , number_of_events_below_threshold INTEGER
    , duration_of_events_below_threshold INTEGER
    , average_respiration FLOAT
    , lowest_respiration FLOAT
    , highest_respiration FLOAT
    , avg_sleep_stress FLOAT
    , breathing_disruption_severity TEXT
    , avg_overnight_hrv FLOAT
    , hrv_status TEXT
    , body_battery_change INTEGER
    , resting_heart_rate INTEGER

    -- Sleep insights and feedback.
    , sleep_score_feedback TEXT
    , sleep_score_insight TEXT
    , sleep_score_personalized_insight TEXT

    -- Sleep scores.
    , total_duration_key TEXT
    , stress_key TEXT
    , awake_count_key TEXT
    , restlessness_key TEXT
    , score_overall_key TEXT
    , score_overall_value INTEGER
    , light_pct_key TEXT
    , light_pct_value INTEGER
    , deep_pct_key TEXT
    , deep_pct_value INTEGER
    , rem_pct_key TEXT
    , rem_pct_value INTEGER

    -- Sleep need.
    , sleep_need_baseline INTEGER
    , sleep_need_actual INTEGER
    , sleep_need_feedback TEXT
    , sleep_need_training_feedback TEXT
    , sleep_need_history_adj TEXT
    , sleep_need_hrv_adj TEXT
    , sleep_need_nap_adj TEXT

    -- Next sleep need.
    , next_sleep_need_baseline INTEGER
    , next_sleep_need_actual INTEGER
    , next_sleep_need_feedback TEXT
    , next_sleep_need_training_feedback TEXT
    , next_sleep_need_history_adj TEXT
    , next_sleep_need_hrv_adj TEXT
    , next_sleep_need_nap_adj TEXT

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
    , update_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()

);

-- Create indexes on sleep table.
CREATE UNIQUE INDEX IF NOT EXISTS sleep_user_id_start_ts_unique_idx
ON garmin.sleep (user_id, start_ts);
CREATE INDEX IF NOT EXISTS sleep_start_ts_brin_idx
ON garmin.sleep USING brin (start_ts);
CREATE INDEX IF NOT EXISTS sleep_end_ts_brin_idx
ON garmin.sleep USING brin (end_ts);
CREATE INDEX IF NOT EXISTS sleep_timezone_offset_hours_idx
ON garmin.sleep (timezone_offset_hours);
CREATE INDEX IF NOT EXISTS sleep_score_overall_key_idx
ON garmin.sleep (score_overall_key);
CREATE INDEX IF NOT EXISTS sleep_hrv_status_idx
ON garmin.sleep (hrv_status);

-- Table comment.
COMMENT ON TABLE garmin.sleep IS
'Sleep session data from Garmin Connect including sleep scores, duration, and '
'quality metrics. Each record represents a single sleep session.';

-- Column comments for sleep table.
COMMENT ON COLUMN garmin.sleep.sleep_id IS
'Auto-incrementing primary key for sleep session records.';
COMMENT ON COLUMN garmin.sleep.user_id IS
'References garmin.user(user_id). Identifies which user had '
'this sleep session.';
COMMENT ON COLUMN garmin.sleep.start_ts IS
'Sleep session start time.';
COMMENT ON COLUMN garmin.sleep.end_ts IS
'Sleep session end time.';
COMMENT ON COLUMN garmin.sleep.timezone_offset_hours IS
'Timezone offset from UTC in hours to infer local time '
'(e.g., -7.0 for UTC-07:00, 5.5 for UTC+05:30).';
COMMENT ON COLUMN garmin.sleep.calendar_date IS
'Calendar date of the sleep session.';
COMMENT ON COLUMN garmin.sleep.sleep_version IS
'Version of sleep tracking algorithm used.';
COMMENT ON COLUMN garmin.sleep.age_group IS
'User age group category.';
COMMENT ON COLUMN garmin.sleep.respiration_version IS
'Version of respiration tracking algorithm used.';
COMMENT ON COLUMN garmin.sleep.sleep_time_seconds IS
'Total sleep time in seconds.';
COMMENT ON COLUMN garmin.sleep.nap_time_seconds IS
'Total nap time in seconds.';
COMMENT ON COLUMN garmin.sleep.unmeasurable_sleep_seconds IS
'Time spent in unmeasurable sleep in seconds.';
COMMENT ON COLUMN garmin.sleep.deep_sleep_seconds IS
'Time spent in deep sleep in seconds.';
COMMENT ON COLUMN garmin.sleep.light_sleep_seconds IS
'Time spent in light sleep in seconds.';
COMMENT ON COLUMN garmin.sleep.rem_sleep_seconds IS
'Time spent in REM sleep in seconds.';
COMMENT ON COLUMN garmin.sleep.awake_sleep_seconds IS
'Time spent awake during sleep session in seconds.';
COMMENT ON COLUMN garmin.sleep.awake_count IS
'Number of times user woke up during sleep.';
COMMENT ON COLUMN garmin.sleep.restless_moments_count IS
'Total count of restless moments during sleep.';
COMMENT ON COLUMN garmin.sleep.rem_sleep_data IS
'Whether REM sleep data is available for this session.';
COMMENT ON COLUMN garmin.sleep.sleep_window_confirmed IS
'Whether the sleep window has been confirmed.';
COMMENT ON COLUMN garmin.sleep.sleep_window_confirmation_type IS
'Type of sleep window confirmation.';
COMMENT ON COLUMN garmin.sleep.sleep_quality_type_pk IS
'Sleep quality type primary key identifier.';
COMMENT ON COLUMN garmin.sleep.sleep_result_type_pk IS
'Sleep result type primary key identifier.';
COMMENT ON COLUMN garmin.sleep.retro IS
'Whether this is a retroactive sleep entry.';
COMMENT ON COLUMN garmin.sleep.sleep_from_device IS
'Whether sleep data came from device or manual entry.';
COMMENT ON COLUMN garmin.sleep.device_rem_capable IS
'Whether the device is capable of REM sleep detection.';
COMMENT ON COLUMN garmin.sleep.skin_temp_data_exists IS
'Whether skin temperature data exists for this session.';
COMMENT ON COLUMN garmin.sleep.average_spo2 IS
'Average SpO2 (blood oxygen saturation) during sleep.';
COMMENT ON COLUMN garmin.sleep.lowest_spo2 IS
'Lowest SpO2 reading during sleep.';
COMMENT ON COLUMN garmin.sleep.highest_spo2 IS
'Highest SpO2 reading during sleep.';
COMMENT ON COLUMN garmin.sleep.average_spo2_hr_sleep IS
'Average heart rate during SpO2 measurements.';
COMMENT ON COLUMN garmin.sleep.number_of_events_below_threshold IS
'Number of SpO2 events below alert threshold.';
COMMENT ON COLUMN garmin.sleep.duration_of_events_below_threshold IS
'Total duration of SpO2 events below threshold in seconds.';
COMMENT ON COLUMN garmin.sleep.average_respiration IS
'Average respiration rate during sleep.';
COMMENT ON COLUMN garmin.sleep.lowest_respiration IS
'Lowest respiration rate during sleep.';
COMMENT ON COLUMN garmin.sleep.highest_respiration IS
'Highest respiration rate during sleep.';
COMMENT ON COLUMN garmin.sleep.avg_sleep_stress IS
'Average stress level during sleep.';
COMMENT ON COLUMN garmin.sleep.breathing_disruption_severity IS
'Severity level of breathing disruptions.';
COMMENT ON COLUMN garmin.sleep.avg_overnight_hrv IS
'Average heart rate variability during sleep.';
COMMENT ON COLUMN garmin.sleep.hrv_status IS
'HRV status classification.';
COMMENT ON COLUMN garmin.sleep.body_battery_change IS
'Change in body battery energy level during sleep.';
COMMENT ON COLUMN garmin.sleep.resting_heart_rate IS
'Resting heart rate measured during sleep.';
COMMENT ON COLUMN garmin.sleep.sleep_score_feedback IS
'Sleep score feedback message.';
COMMENT ON COLUMN garmin.sleep.sleep_score_insight IS
'Sleep score insight message.';
COMMENT ON COLUMN garmin.sleep.sleep_score_personalized_insight IS
'Personalized sleep score insight message.';
COMMENT ON COLUMN garmin.sleep.total_duration_key IS
'Sleep duration quality qualifier key.';
COMMENT ON COLUMN garmin.sleep.stress_key IS
'Sleep stress level quality qualifier key.';
COMMENT ON COLUMN garmin.sleep.awake_count_key IS
'Number of awakenings quality qualifier key.';
COMMENT ON COLUMN garmin.sleep.restlessness_key IS
'Sleep restlessness quality qualifier key.';
COMMENT ON COLUMN garmin.sleep.score_overall_key IS
'Overall sleep score quality qualifier key.';
COMMENT ON COLUMN garmin.sleep.score_overall_value IS
'Overall sleep score numeric value (0-100 scale).';
COMMENT ON COLUMN garmin.sleep.light_pct_key IS
'Light sleep percentage quality qualifier key.';
COMMENT ON COLUMN garmin.sleep.light_pct_value IS
'Light sleep percentage numeric value.';
COMMENT ON COLUMN garmin.sleep.deep_pct_key IS
'Deep sleep percentage quality qualifier key.';
COMMENT ON COLUMN garmin.sleep.deep_pct_value IS
'Deep sleep percentage numeric value.';
COMMENT ON COLUMN garmin.sleep.rem_pct_key IS
'REM sleep percentage quality qualifier key.';
COMMENT ON COLUMN garmin.sleep.rem_pct_value IS
'REM sleep percentage numeric value.';
COMMENT ON COLUMN garmin.sleep.sleep_need_baseline IS
'Baseline sleep need in minutes.';
COMMENT ON COLUMN garmin.sleep.sleep_need_actual IS
'Actual sleep need in minutes.';
COMMENT ON COLUMN garmin.sleep.sleep_need_feedback IS
'Sleep need feedback.';
COMMENT ON COLUMN garmin.sleep.sleep_need_training_feedback IS
'Training-related sleep need feedback.';
COMMENT ON COLUMN garmin.sleep.sleep_need_history_adj IS
'Sleep history adjustment factor.';
COMMENT ON COLUMN garmin.sleep.sleep_need_hrv_adj IS
'HRV-based sleep need adjustment.';
COMMENT ON COLUMN garmin.sleep.sleep_need_nap_adj IS
'Nap-based sleep need adjustment.';
COMMENT ON COLUMN garmin.sleep.next_sleep_need_baseline IS
'Next day baseline sleep need in minutes.';
COMMENT ON COLUMN garmin.sleep.next_sleep_need_actual IS
'Next day actual sleep need in minutes.';
COMMENT ON COLUMN garmin.sleep.next_sleep_need_feedback IS
'Next day sleep need feedback.';
COMMENT ON COLUMN garmin.sleep.next_sleep_need_training_feedback IS
'Next day training-related sleep need feedback.';
COMMENT ON COLUMN garmin.sleep.next_sleep_need_history_adj IS
'Next day sleep history adjustment factor.';
COMMENT ON COLUMN garmin.sleep.next_sleep_need_hrv_adj IS
'Next day HRV-based sleep need adjustment.';
COMMENT ON COLUMN garmin.sleep.next_sleep_need_nap_adj IS
'Next day nap-based sleep need adjustment.';
COMMENT ON COLUMN garmin.sleep.create_ts IS
'Timestamp when the record was created in the database.';
COMMENT ON COLUMN garmin.sleep.update_ts IS
'Timestamp when the record was last modified in the database.';

----------------------------------------------------------------------------------------

-- Sleep movement activity levels during sleep sessions.
-- Time interval: 1 minute intervals.
CREATE TABLE IF NOT EXISTS garmin.sleep_movement (
    sleep_id INTEGER REFERENCES garmin.sleep (sleep_id) ON DELETE CASCADE
    , timestamp TIMESTAMPTZ
    , activity_level FLOAT

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()

    -- Primary key.
    , PRIMARY KEY (sleep_id, timestamp)
);

-- Create indexes on sleep_movement table.
CREATE INDEX IF NOT EXISTS sleep_movement_sleep_id_idx
ON garmin.sleep_movement (sleep_id);
CREATE INDEX IF NOT EXISTS sleep_movement_timestamp_brin_idx
ON garmin.sleep_movement USING brin (timestamp);
CREATE INDEX IF NOT EXISTS sleep_movement_activity_level_idx
ON garmin.sleep_movement (activity_level);

-- Table comment.
COMMENT ON TABLE garmin.sleep_movement IS
'Sleep movement activity levels at regular 1-minute intervals throughout sleep '
'sessions. Higher values indicate more movement.';

-- Column comments for sleep_movement table.
COMMENT ON COLUMN garmin.sleep_movement.sleep_id IS
'References the sleep session identifier.';
COMMENT ON COLUMN garmin.sleep_movement.timestamp IS
'Timestamp of the movement measurement.';
COMMENT ON COLUMN garmin.sleep_movement.activity_level IS
'Movement activity level (higher values indicate more movement).';
COMMENT ON COLUMN garmin.sleep_movement.create_ts IS
'Timestamp when the record was created in the database.';

----------------------------------------------------------------------------------------

-- Sleep restless moments during sleep sessions.
-- Time interval: Event-based (irregular intervals when restless moments occur).
CREATE TABLE IF NOT EXISTS garmin.sleep_restless_moment (
    sleep_id INTEGER REFERENCES garmin.sleep (sleep_id) ON DELETE CASCADE
    , timestamp TIMESTAMPTZ
    , value INTEGER

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()

    -- Primary key.
    , PRIMARY KEY (sleep_id, timestamp)
);

-- Create indexes on sleep_restless_moment table.
CREATE INDEX IF NOT EXISTS sleep_restless_moment_sleep_id_idx
ON garmin.sleep_restless_moment (sleep_id);
CREATE INDEX IF NOT EXISTS sleep_restless_moment_timestamp_brin_idx
ON garmin.sleep_restless_moment USING brin (timestamp);
CREATE INDEX IF NOT EXISTS sleep_restless_moment_value_idx
ON garmin.sleep_restless_moment (value);

-- Table comment.
COMMENT ON TABLE garmin.sleep_restless_moment IS
'Sleep restless moments count capturing periods of restlessness or movement '
'during sleep sessions.';

-- Column comments for sleep_restless_moment table.
COMMENT ON COLUMN garmin.sleep_restless_moment.sleep_id IS
'References the sleep session identifier.';
COMMENT ON COLUMN garmin.sleep_restless_moment.timestamp IS
'Timestamp of the restless moment.';
COMMENT ON COLUMN garmin.sleep_restless_moment.value IS
'Restless moments count.';
COMMENT ON COLUMN garmin.sleep_restless_moment.create_ts IS
'Timestamp when the record was created in the database.';

----------------------------------------------------------------------------------------

-- Blood oxygen saturation (SpO2) readings during sleep.
-- Time interval: 1 minute intervals during sleep.
CREATE TABLE IF NOT EXISTS garmin.spo2 (
    sleep_id INTEGER REFERENCES garmin.sleep (sleep_id) ON DELETE CASCADE
    , timestamp TIMESTAMPTZ
    , value INTEGER

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()

    -- Primary key.
    , PRIMARY KEY (sleep_id, timestamp)
);

-- Create indexes on spo2 table.
CREATE INDEX IF NOT EXISTS spo2_sleep_id_idx
ON garmin.spo2 (sleep_id);
CREATE INDEX IF NOT EXISTS spo2_timestamp_brin_idx
ON garmin.spo2 USING brin (timestamp);
CREATE INDEX IF NOT EXISTS spo2_value_idx
ON garmin.spo2 (value);

-- Table comment.
COMMENT ON TABLE garmin.spo2 IS
'Blood oxygen saturation (SpO2) measurements at regular 1-minute intervals during '
'sleep sessions.';

-- Column comments for spo2 table.
COMMENT ON COLUMN garmin.spo2.sleep_id IS
'References the sleep session identifier.';
COMMENT ON COLUMN garmin.spo2.timestamp IS
'Timestamp of the SpO2 measurement.';
COMMENT ON COLUMN garmin.spo2.value IS
'SpO2 reading as percentage (typically 85-100).';
COMMENT ON COLUMN garmin.spo2.create_ts IS
'Timestamp when the record was created in the database.';

----------------------------------------------------------------------------------------

-- Heart rate variability (HRV) data during sleep sessions.
-- Time interval: 5 minute intervals.
CREATE TABLE IF NOT EXISTS garmin.hrv (
    sleep_id INTEGER REFERENCES garmin.sleep (sleep_id) ON DELETE CASCADE
    , timestamp TIMESTAMPTZ
    , value FLOAT

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()

    -- Primary key.
    , PRIMARY KEY (sleep_id, timestamp)
);

-- Create indexes on hrv table.
CREATE INDEX IF NOT EXISTS hrv_sleep_id_idx
ON garmin.hrv (sleep_id);
CREATE INDEX IF NOT EXISTS hrv_timestamp_brin_idx
ON garmin.hrv USING brin (timestamp);
CREATE INDEX IF NOT EXISTS hrv_value_idx
ON garmin.hrv (value);

-- Table comment.
COMMENT ON TABLE garmin.hrv IS
'Heart rate variability (HRV) measurements at regular 5-minute intervals throughout '
'sleep periods indicating autonomic nervous system recovery.';

-- Column comments for hrv table.
COMMENT ON COLUMN garmin.hrv.sleep_id IS
'References the sleep session identifier.';
COMMENT ON COLUMN garmin.hrv.timestamp IS
'Timestamp of the HRV measurement.';
COMMENT ON COLUMN garmin.hrv.value IS
'HRV value in milliseconds.';
COMMENT ON COLUMN garmin.hrv.create_ts IS
'Timestamp when the record was created in the database.';

----------------------------------------------------------------------------------------

-- Breathing disruption events during sleep sessions.
-- Time interval: Event-based (irregular intervals when breathing disruptions occur).
CREATE TABLE IF NOT EXISTS garmin.breathing_disruption (
    sleep_id INTEGER REFERENCES garmin.sleep (sleep_id) ON DELETE CASCADE
    , timestamp TIMESTAMPTZ
    , value INTEGER

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()

    -- Primary key.
    , PRIMARY KEY (sleep_id, timestamp)
);

-- Create indexes on breathing_disruption table.
CREATE INDEX IF NOT EXISTS breathing_disruption_sleep_id_idx
ON garmin.breathing_disruption (sleep_id);
CREATE INDEX IF NOT EXISTS breathing_disruption_timestamp_brin_idx
ON garmin.breathing_disruption USING brin (timestamp);
CREATE INDEX IF NOT EXISTS breathing_disruption_value_idx
ON garmin.breathing_disruption (value);

-- Table comment.
COMMENT ON TABLE garmin.breathing_disruption IS
'Breathing disruption events and their severity during sleep periods '
'indicating potential sleep apnea or breathing irregularities.';

-- Column comments for breathing_disruption table.
COMMENT ON COLUMN garmin.breathing_disruption.sleep_id IS
'References the sleep session identifier.';
COMMENT ON COLUMN garmin.breathing_disruption.timestamp IS
'Timestamp of the breathing disruption event.';
COMMENT ON COLUMN garmin.breathing_disruption.value IS
'Breathing disruption severity or type indicator.';
COMMENT ON COLUMN garmin.breathing_disruption.create_ts IS
'Timestamp when the record was created in the database.';

----------------------------------------------------------------------------------------

-- VO2 max data from training status including generic and cycling measurements.
CREATE TABLE IF NOT EXISTS garmin.vo2_max (
    user_id BIGINT REFERENCES garmin.user (user_id)
    , date DATE
    , vo2_max_generic FLOAT
    , vo2_max_cycling FLOAT

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
    , update_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()

    -- Primary key.
    , PRIMARY KEY (user_id, date)
);

CREATE INDEX IF NOT EXISTS vo2_max_user_id_idx
ON garmin.vo2_max (user_id);
CREATE INDEX IF NOT EXISTS vo2_max_date_brin_idx
ON garmin.vo2_max USING brin (date);

-- Table comment.
COMMENT ON TABLE garmin.vo2_max IS
'VO2 max measurements from Garmin training status data including both generic '
'and cycling-specific values.';

-- Column comments.
COMMENT ON COLUMN garmin.vo2_max.user_id IS
'References garmin.user(user_id). Identifies which user '
'this VO2 max measurement belongs to.';
COMMENT ON COLUMN garmin.vo2_max.date IS
'Calendar date of the VO2 max measurement.';
COMMENT ON COLUMN garmin.vo2_max.vo2_max_generic IS
'Generic VO2 max value in ml/kg/min.';
COMMENT ON COLUMN garmin.vo2_max.vo2_max_cycling IS
'Cycling-specific VO2 max value in ml/kg/min.';
COMMENT ON COLUMN garmin.vo2_max.create_ts IS
'Timestamp when the record was created in the database.';
COMMENT ON COLUMN garmin.vo2_max.update_ts IS
'Timestamp when the record was last modified in the database.';

----------------------------------------------------------------------------------------

-- Heat and altitude acclimation data from training status.
CREATE TABLE IF NOT EXISTS garmin.acclimation (
    user_id BIGINT REFERENCES garmin.user (user_id)
    , date DATE
    , altitude_acclimation FLOAT
    , heat_acclimation_percentage FLOAT
    , current_altitude FLOAT
    , acclimation_percentage FLOAT
    , altitude_trend TEXT
    , heat_trend TEXT

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
    , update_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()

    -- Primary key.
    , PRIMARY KEY (user_id, date)
);

CREATE INDEX IF NOT EXISTS acclimation_user_id_idx
ON garmin.acclimation (user_id);
CREATE INDEX IF NOT EXISTS acclimation_date_brin_idx
ON garmin.acclimation USING brin (date);
CREATE INDEX IF NOT EXISTS acclimation_altitude_trend_idx
ON garmin.acclimation (altitude_trend);
CREATE INDEX IF NOT EXISTS acclimation_heat_trend_idx
ON garmin.acclimation (heat_trend);

-- Table comment.
COMMENT ON TABLE garmin.acclimation IS
'Heat and altitude acclimation metrics from Garmin training status data.';

-- Column comments.
COMMENT ON COLUMN garmin.acclimation.user_id IS
'References garmin.user(user_id). Identifies which user this acclimation data belongs '
'to.';
COMMENT ON COLUMN garmin.acclimation.date IS
'Calendar date of the acclimation measurement.';
COMMENT ON COLUMN garmin.acclimation.altitude_acclimation IS
'Altitude acclimation level as a numeric value.';
COMMENT ON COLUMN garmin.acclimation.heat_acclimation_percentage IS
'Heat acclimation level as a percentage (0-100).';
COMMENT ON COLUMN garmin.acclimation.current_altitude IS
'Current altitude in meters.';
COMMENT ON COLUMN garmin.acclimation.acclimation_percentage IS
'Overall acclimation percentage.';
COMMENT ON COLUMN garmin.acclimation.altitude_trend IS
'Altitude acclimation trend (e.g., ''MAINTAINING'', ''GAINING'').';
COMMENT ON COLUMN garmin.acclimation.heat_trend IS
'Heat acclimation trend (e.g., ''DEACCLIMATIZING'', ''ACCLIMATIZING'').';
COMMENT ON COLUMN garmin.acclimation.create_ts IS
'Timestamp when the record was created in the database.';
COMMENT ON COLUMN garmin.acclimation.update_ts IS
'Timestamp when the record was last modified in the database.';

----------------------------------------------------------------------------------------

-- Training load and status data including monthly load balance and ACWR metrics.
CREATE TABLE IF NOT EXISTS garmin.training_load (
    user_id BIGINT REFERENCES garmin.user (user_id)
    , date DATE

    -- Monthly training load balance.
    , monthly_load_aerobic_low FLOAT
    , monthly_load_aerobic_high FLOAT
    , monthly_load_anaerobic FLOAT
    , monthly_load_aerobic_low_target_min FLOAT
    , monthly_load_aerobic_low_target_max FLOAT
    , monthly_load_aerobic_high_target_min FLOAT
    , monthly_load_aerobic_high_target_max FLOAT
    , monthly_load_anaerobic_target_min FLOAT
    , monthly_load_anaerobic_target_max FLOAT
    , training_balance_feedback_phrase TEXT

    -- Acute chronic workload ratio (ACWR) metrics.
    , acwr_percent FLOAT
    , acwr_status TEXT
    , acwr_status_feedback TEXT
    , daily_training_load_acute FLOAT
    , max_training_load_chronic FLOAT
    , min_training_load_chronic FLOAT
    , daily_training_load_chronic FLOAT
    , daily_acute_chronic_workload_ratio FLOAT

    -- Training status.
    , training_status INTEGER
    , training_status_feedback_phrase TEXT

    -- Intensity minutes.
    , total_intensity_minutes INTEGER
    , moderate_minutes INTEGER
    , vigorous_minutes INTEGER

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
    , update_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()

    -- Primary key.
    , PRIMARY KEY (user_id, date)
);

CREATE INDEX IF NOT EXISTS training_load_user_id_idx
ON garmin.training_load (user_id);
CREATE INDEX IF NOT EXISTS training_load_date_brin_idx
ON garmin.training_load USING brin (date);
CREATE INDEX IF NOT EXISTS training_load_training_balance_feedback_phrase_idx
ON garmin.training_load (training_balance_feedback_phrase);
CREATE INDEX IF NOT EXISTS training_load_acwr_status_idx
ON garmin.training_load (acwr_status);
CREATE INDEX IF NOT EXISTS training_load_training_status_idx
ON garmin.training_load (training_status);

-- Table comment.
COMMENT ON TABLE garmin.training_load IS
'Training load balance and status metrics from Garmin Connect including '
'monthly low/high aerobic/anaerobic load distribution, ACWR Acute:Chronic Workload '
'Ratio (ACWR) analysis, and training status indicators.';

-- Column comments.
COMMENT ON COLUMN garmin.training_load.user_id IS
'References garmin.user(user_id). Identifies which user '
'this training load data belongs to.';
COMMENT ON COLUMN garmin.training_load.date IS
'Calendar date of the training load measurement.';
COMMENT ON COLUMN garmin.training_load.monthly_load_aerobic_low IS
'Monthly aerobic low intensity training load.';
COMMENT ON COLUMN garmin.training_load.monthly_load_aerobic_high IS
'Monthly aerobic high intensity training load.';
COMMENT ON COLUMN garmin.training_load.monthly_load_anaerobic IS
'Monthly anaerobic training load.';
COMMENT ON COLUMN garmin.training_load.monthly_load_aerobic_low_target_min IS
'Minimum target for monthly aerobic low intensity load.';
COMMENT ON COLUMN garmin.training_load.monthly_load_aerobic_low_target_max IS
'Maximum target for monthly aerobic low intensity load.';
COMMENT ON COLUMN garmin.training_load.monthly_load_aerobic_high_target_min IS
'Minimum target for monthly aerobic high intensity load.';
COMMENT ON COLUMN garmin.training_load.monthly_load_aerobic_high_target_max IS
'Maximum target for monthly aerobic high intensity load.';
COMMENT ON COLUMN garmin.training_load.monthly_load_anaerobic_target_min IS
'Minimum target for monthly anaerobic load.';
COMMENT ON COLUMN garmin.training_load.monthly_load_anaerobic_target_max IS
'Maximum target for monthly anaerobic load.';
COMMENT ON COLUMN garmin.training_load.training_balance_feedback_phrase IS
'Training balance feedback message (e.g., ''ABOVE_TARGETS'').';
COMMENT ON COLUMN garmin.training_load.acwr_percent IS
'Acute chronic workload ratio as a percentage.';
COMMENT ON COLUMN garmin.training_load.acwr_status IS
'ACWR status classification (e.g., ''OPTIMAL'').';
COMMENT ON COLUMN garmin.training_load.acwr_status_feedback IS
'ACWR status feedback message.';
COMMENT ON COLUMN garmin.training_load.daily_training_load_acute IS
'Daily acute training load value.';
COMMENT ON COLUMN garmin.training_load.max_training_load_chronic IS
'Maximum chronic training load threshold.';
COMMENT ON COLUMN garmin.training_load.min_training_load_chronic IS
'Minimum chronic training load threshold.';
COMMENT ON COLUMN garmin.training_load.daily_training_load_chronic IS
'Daily chronic training load value.';
COMMENT ON COLUMN garmin.training_load.daily_acute_chronic_workload_ratio IS
'Daily acute to chronic workload ratio.';
COMMENT ON COLUMN garmin.training_load.training_status IS
'Training status numeric code.';
COMMENT ON COLUMN garmin.training_load.training_status_feedback_phrase IS
'Training status feedback message (e.g., ''STRAINED_1'').';
COMMENT ON COLUMN garmin.training_load.total_intensity_minutes IS
'Total intensity minutes calculated as endDayMinutes - startDayMinutes.';
COMMENT ON COLUMN garmin.training_load.moderate_minutes IS
'Daily moderate intensity minutes from intensity minutes tracking.';
COMMENT ON COLUMN garmin.training_load.vigorous_minutes IS
'Daily vigorous intensity minutes from intensity minutes tracking.';
COMMENT ON COLUMN garmin.training_load.create_ts IS
'Timestamp when the record was created in the database.';
COMMENT ON COLUMN garmin.training_load.update_ts IS
'Timestamp when the record was last modified in the database.';

----------------------------------------------------------------------------------------

-- Training readiness data providing insights into recovery and training capacity.
CREATE TABLE IF NOT EXISTS garmin.training_readiness (
    user_id BIGINT REFERENCES garmin.user (user_id)
    , timestamp TIMESTAMPTZ
    , timezone_offset_hours FLOAT NOT NULL

    -- Training readiness metrics.
    , level TEXT
    , feedback_long TEXT
    , feedback_short TEXT
    , score INTEGER
    , sleep_score INTEGER
    , sleep_score_factor_percent INTEGER
    , sleep_score_factor_feedback TEXT
    , recovery_time INTEGER
    , recovery_time_factor_percent INTEGER
    , recovery_time_factor_feedback TEXT
    , acwr_factor_percent INTEGER
    , acwr_factor_feedback TEXT
    , acute_load INTEGER
    , stress_history_factor_percent INTEGER
    , stress_history_factor_feedback TEXT
    , hrv_factor_percent INTEGER
    , hrv_factor_feedback TEXT
    , hrv_weekly_average INTEGER
    , sleep_history_factor_percent INTEGER
    , sleep_history_factor_feedback TEXT
    , valid_sleep BOOLEAN
    , input_context TEXT
    , primary_activity_tracker BOOLEAN
    , recovery_time_change_phrase TEXT
    , sleep_history_factor_feedback_phrase TEXT
    , hrv_factor_feedback_phrase TEXT
    , stress_history_factor_feedback_phrase TEXT
    , acwr_factor_feedback_phrase TEXT
    , recovery_time_factor_feedback_phrase TEXT
    , sleep_score_factor_feedback_phrase TEXT

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
    , update_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()

    -- Primary key.
    , PRIMARY KEY (user_id, timestamp)
);

CREATE INDEX IF NOT EXISTS training_readiness_user_id_idx
ON garmin.training_readiness (user_id);
CREATE INDEX IF NOT EXISTS training_readiness_timestamp_brin_idx
ON garmin.training_readiness USING brin (timestamp);
CREATE INDEX IF NOT EXISTS training_readiness_timezone_offset_hours_idx
ON garmin.training_readiness (timezone_offset_hours);
CREATE INDEX IF NOT EXISTS training_readiness_level_idx
ON garmin.training_readiness (level);
CREATE INDEX IF NOT EXISTS training_readiness_score_idx
ON garmin.training_readiness (score);
CREATE INDEX IF NOT EXISTS training_readiness_sleep_score_factor_percent_idx
ON garmin.training_readiness (sleep_score_factor_percent);
CREATE INDEX IF NOT EXISTS training_readiness_sleep_score_factor_feedback_idx
ON garmin.training_readiness (sleep_score_factor_feedback);
CREATE INDEX IF NOT EXISTS training_readiness_recovery_time_idx
ON garmin.training_readiness (recovery_time);
CREATE INDEX IF NOT EXISTS training_readiness_recovery_time_factor_percent_idx
ON garmin.training_readiness (recovery_time_factor_percent);
CREATE INDEX IF NOT EXISTS training_readiness_recovery_time_factor_feedback_idx
ON garmin.training_readiness (recovery_time_factor_feedback);
CREATE INDEX IF NOT EXISTS training_readiness_acwr_factor_percent_idx
ON garmin.training_readiness (acwr_factor_percent);
CREATE INDEX IF NOT EXISTS training_readiness_acwr_factor_feedback_idx
ON garmin.training_readiness (acwr_factor_feedback);
CREATE INDEX IF NOT EXISTS training_readiness_acute_load_idx
ON garmin.training_readiness (acute_load);
CREATE INDEX IF NOT EXISTS training_readiness_stress_history_factor_percent_idx
ON garmin.training_readiness (stress_history_factor_percent);
CREATE INDEX IF NOT EXISTS training_readiness_stress_history_factor_feedback_idx
ON garmin.training_readiness (stress_history_factor_feedback);
CREATE INDEX IF NOT EXISTS training_readiness_hrv_factor_percent_idx
ON garmin.training_readiness (hrv_factor_percent);
CREATE INDEX IF NOT EXISTS training_readiness_hrv_factor_feedback_idx
ON garmin.training_readiness (hrv_factor_feedback);
CREATE INDEX IF NOT EXISTS training_readiness_hrv_weekly_average_idx
ON garmin.training_readiness (hrv_weekly_average);
CREATE INDEX IF NOT EXISTS training_readiness_sleep_history_factor_percent_idx
ON garmin.training_readiness (sleep_history_factor_percent);
CREATE INDEX IF NOT EXISTS training_readiness_sleep_history_factor_feedback_idx
ON garmin.training_readiness (sleep_history_factor_feedback);

-- Table comment.
COMMENT ON TABLE garmin.training_readiness IS
'Training readiness scores and factors from Garmin Connect indicating recovery '
'status and training capacity based on sleep, HRV, stress, and training load metrics.';

-- Column comments.
COMMENT ON COLUMN garmin.training_readiness.user_id IS
'References garmin.user(user_id). Identifies which user '
'this training readiness data belongs to.';
COMMENT ON COLUMN garmin.training_readiness.timestamp IS
'Training readiness measurement timestamp.';
COMMENT ON COLUMN garmin.training_readiness.timezone_offset_hours IS
'Timezone offset from UTC in hours to infer local time '
'(e.g., -7.0 for UTC-07:00, 5.5 for UTC+05:30).';
COMMENT ON COLUMN garmin.training_readiness.level IS
'Training readiness level (e.g., ''HIGH'', ''MODERATE'', ''LOW'').';
COMMENT ON COLUMN garmin.training_readiness.feedback_long IS
'Detailed training readiness feedback message.';
COMMENT ON COLUMN garmin.training_readiness.feedback_short IS
'Short training readiness feedback message.';
COMMENT ON COLUMN garmin.training_readiness.score IS
'Overall training readiness score (0-100 scale).';
COMMENT ON COLUMN garmin.training_readiness.sleep_score IS
'Sleep quality score contributing to training readiness.';
COMMENT ON COLUMN garmin.training_readiness.sleep_score_factor_percent IS
'Sleep score contribution percentage to overall readiness.';
COMMENT ON COLUMN garmin.training_readiness.sleep_score_factor_feedback IS
'Sleep score factor feedback (e.g., ''MODERATE'', ''GOOD'').';
COMMENT ON COLUMN garmin.training_readiness.recovery_time IS
'Estimated recovery time in minutes.';
COMMENT ON COLUMN garmin.training_readiness.recovery_time_factor_percent IS
'Recovery time contribution percentage to overall readiness.';
COMMENT ON COLUMN garmin.training_readiness.recovery_time_factor_feedback IS
'Recovery time factor feedback (e.g., ''MODERATE'', ''GOOD'').';
COMMENT ON COLUMN garmin.training_readiness.acwr_factor_percent IS
'Acute chronic workload ratio contribution percentage to overall readiness.';
COMMENT ON COLUMN garmin.training_readiness.acwr_factor_feedback IS
'ACWR factor feedback (e.g., ''GOOD'', ''VERY_GOOD'').';
COMMENT ON COLUMN garmin.training_readiness.acute_load IS
'Acute training load value.';
COMMENT ON COLUMN garmin.training_readiness.stress_history_factor_percent IS
'Stress history contribution percentage to overall readiness.';
COMMENT ON COLUMN garmin.training_readiness.stress_history_factor_feedback IS
'Stress history factor feedback (e.g., ''GOOD'').';
COMMENT ON COLUMN garmin.training_readiness.hrv_factor_percent IS
'Heart rate variability contribution percentage to overall readiness.';
COMMENT ON COLUMN garmin.training_readiness.hrv_factor_feedback IS
'HRV factor feedback (e.g., ''GOOD'').';
COMMENT ON COLUMN garmin.training_readiness.hrv_weekly_average IS
'Weekly average HRV value in milliseconds.';
COMMENT ON COLUMN garmin.training_readiness.sleep_history_factor_percent IS
'Sleep history contribution percentage to overall readiness.';
COMMENT ON COLUMN garmin.training_readiness.sleep_history_factor_feedback IS
'Sleep history factor feedback (e.g., ''MODERATE'').';
COMMENT ON COLUMN garmin.training_readiness.valid_sleep IS
'Whether sleep data is valid and available for calculation.';
COMMENT ON COLUMN garmin.training_readiness.input_context IS
'Context of the training readiness calculation (e.g., ''UPDATE_REALTIME_VARIABLES'').';
COMMENT ON COLUMN garmin.training_readiness.primary_activity_tracker IS
'Whether this device is the primary activity tracker.';
COMMENT ON COLUMN garmin.training_readiness.recovery_time_change_phrase IS
'Recovery time change feedback phrase.';
COMMENT ON COLUMN garmin.training_readiness.sleep_history_factor_feedback_phrase IS
'Sleep history factor detailed feedback phrase.';
COMMENT ON COLUMN garmin.training_readiness.hrv_factor_feedback_phrase IS
'HRV factor detailed feedback phrase.';
COMMENT ON COLUMN garmin.training_readiness.stress_history_factor_feedback_phrase IS
'Stress history factor detailed feedback phrase.';
COMMENT ON COLUMN garmin.training_readiness.acwr_factor_feedback_phrase IS
'ACWR factor detailed feedback phrase.';
COMMENT ON COLUMN garmin.training_readiness.recovery_time_factor_feedback_phrase IS
'Recovery time factor detailed feedback phrase.';
COMMENT ON COLUMN garmin.training_readiness.sleep_score_factor_feedback_phrase IS
'Sleep score factor detailed feedback phrase.';
COMMENT ON COLUMN garmin.training_readiness.create_ts IS
'Timestamp when the record was created in the database.';
COMMENT ON COLUMN garmin.training_readiness.update_ts IS
'Timestamp when the record was last modified in the database.';

----------------------------------------------------------------------------------------

-- Stress level timeseries data capturing stress measurements throughout the day.
-- Time interval: 3 minute intervals (~180 seconds).
CREATE TABLE IF NOT EXISTS garmin.stress (
    user_id BIGINT REFERENCES garmin.user (user_id)
    , timestamp TIMESTAMPTZ
    , value INTEGER

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()

    -- Primary key.
    , PRIMARY KEY (user_id, timestamp)
);

-- Create indexes on stress table.
CREATE INDEX IF NOT EXISTS stress_user_id_idx
ON garmin.stress (user_id);
CREATE INDEX IF NOT EXISTS stress_timestamp_brin_idx
ON garmin.stress USING brin (timestamp);
CREATE INDEX IF NOT EXISTS stress_value_idx
ON garmin.stress (value);

-- Table comment.
COMMENT ON TABLE garmin.stress IS
'Stress level measurements at regular 3-minute intervals throughout the day. '
'Stress values typically range from 0-100, with negative values indicating '
'unmeasurable periods.';

-- Column comments for stress table.
COMMENT ON COLUMN garmin.stress.user_id IS
'References garmin.user(user_id). Identifies which user '
'this stress measurement belongs to.';
COMMENT ON COLUMN garmin.stress.timestamp IS
'Timestamp of the stress measurement.';
COMMENT ON COLUMN garmin.stress.value IS
'Stress level value (0-100 scale, negative values indicate unmeasurable periods).';
COMMENT ON COLUMN garmin.stress.create_ts IS
'Timestamp when the record was created in the database.';

----------------------------------------------------------------------------------------

-- Body battery level timeseries data capturing energy levels throughout the day.
-- Time interval: 3 minute intervals (~180 seconds).
CREATE TABLE IF NOT EXISTS garmin.body_battery (
    user_id BIGINT REFERENCES garmin.user (user_id)
    , timestamp TIMESTAMPTZ
    , value INTEGER

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()

    -- Primary key.
    , PRIMARY KEY (user_id, timestamp)
);

-- Create indexes on body_battery table.
CREATE INDEX IF NOT EXISTS body_battery_user_id_idx
ON garmin.body_battery (user_id);
CREATE INDEX IF NOT EXISTS body_battery_timestamp_brin_idx
ON garmin.body_battery USING brin (timestamp);
CREATE INDEX IF NOT EXISTS body_battery_value_idx
ON garmin.body_battery (value);

-- Table comment.
COMMENT ON TABLE garmin.body_battery IS
'Body battery energy level measurements at regular 3-minute intervals '
'throughout the day. Body battery values typically range from 0-100.';

-- Column comments for body_battery table.
COMMENT ON COLUMN garmin.body_battery.user_id IS
'References garmin.user(user_id). Identifies which user '
'this body battery measurement belongs to.';
COMMENT ON COLUMN garmin.body_battery.timestamp IS
'Timestamp of the body battery measurement.';
COMMENT ON COLUMN garmin.body_battery.value IS
'Body battery energy level (0-100 scale).';
COMMENT ON COLUMN garmin.body_battery.create_ts IS
'Timestamp when the record was created in the database.';

----------------------------------------------------------------------------------------

-- Heart rate data from Garmin devices at regular 2-minute intervals.
CREATE TABLE IF NOT EXISTS garmin.heart_rate (
    user_id BIGINT REFERENCES garmin.user (user_id)
    , timestamp TIMESTAMPTZ
    , value INTEGER

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()

    -- Primary key.
    , PRIMARY KEY (user_id, timestamp)
);

-- Create indexes on heart_rate table.
CREATE INDEX IF NOT EXISTS heart_rate_user_id_idx
ON garmin.heart_rate (user_id);
CREATE INDEX IF NOT EXISTS heart_rate_timestamp_brin_idx
ON garmin.heart_rate USING brin (timestamp);
CREATE INDEX IF NOT EXISTS heart_rate_value_idx
ON garmin.heart_rate (value);

-- Table comment.
COMMENT ON TABLE garmin.heart_rate IS
'Heart rate measurements from Garmin devices at regular 2-minute intervals '
'during periods when heart rate monitoring is active.';

-- Column comments for heart_rate table.
COMMENT ON COLUMN garmin.heart_rate.user_id IS
'References garmin.user(user_id). Identifies which user '
'this heart rate measurement belongs to.';
COMMENT ON COLUMN garmin.heart_rate.timestamp IS
'Timestamp of the heart rate measurement.';
COMMENT ON COLUMN garmin.heart_rate.value IS
'Heart rate value in beats per minute.';
COMMENT ON COLUMN garmin.heart_rate.create_ts IS
'Timestamp when the record was created in the database.';

----------------------------------------------------------------------------------------

-- Step count data from Garmin devices at regular 15-minute intervals.
CREATE TABLE IF NOT EXISTS garmin.steps (
    user_id BIGINT REFERENCES garmin.user (user_id)
    , timestamp TIMESTAMPTZ
    , value INTEGER
    , activity_level TEXT
    , activity_level_constant BOOLEAN

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()

    -- Primary key.
    , PRIMARY KEY (user_id, timestamp)
);

-- Create indexes on steps table.
CREATE INDEX IF NOT EXISTS steps_user_id_idx
ON garmin.steps (user_id);
CREATE INDEX IF NOT EXISTS steps_timestamp_brin_idx
ON garmin.steps USING brin (timestamp);
CREATE INDEX IF NOT EXISTS steps_value_idx
ON garmin.steps (value);
CREATE INDEX IF NOT EXISTS steps_activity_level_idx
ON garmin.steps (activity_level);
CREATE INDEX IF NOT EXISTS steps_activity_level_constant_idx
ON garmin.steps (activity_level_constant);

-- Table comment.
COMMENT ON TABLE garmin.steps IS
'Step count measurements from Garmin devices at regular 15-minute intervals '
'throughout the day including activity level and consistency indicators.';

-- Column comments for steps table.
COMMENT ON COLUMN garmin.steps.user_id IS
'References garmin.user(user_id). Identifies which user '
'this step count measurement belongs to.';
COMMENT ON COLUMN garmin.steps.timestamp IS
'Timestamp of the step count measurement.';
COMMENT ON COLUMN garmin.steps.value IS
'Number of steps taken during the 15-minute interval.';
COMMENT ON COLUMN garmin.steps.activity_level IS
'Activity level classification (e.g., sleeping, sedentary, active, highlyActive).';
COMMENT ON COLUMN garmin.steps.activity_level_constant IS
'Whether the activity level remained constant during the interval.';
COMMENT ON COLUMN garmin.steps.create_ts IS
'Timestamp when the record was created in the database.';

----------------------------------------------------------------------------------------

-- Respiration rate data from Garmin devices at regular 2-minute intervals.
CREATE TABLE IF NOT EXISTS garmin.respiration (
    user_id BIGINT REFERENCES garmin.user (user_id)
    , timestamp TIMESTAMPTZ
    , value FLOAT

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()

    -- Primary key.
    , PRIMARY KEY (user_id, timestamp)
);

-- Create indexes on respiration table.
CREATE INDEX IF NOT EXISTS respiration_user_id_idx
ON garmin.respiration (user_id);
CREATE INDEX IF NOT EXISTS respiration_timestamp_brin_idx
ON garmin.respiration USING brin (timestamp);
CREATE INDEX IF NOT EXISTS respiration_value_idx
ON garmin.respiration (value);

-- Table comment.
COMMENT ON TABLE garmin.respiration IS
'Respiration rate measurements from Garmin devices at regular 2-minute intervals '
'throughout the day during periods when respiration monitoring is active.';

-- Column comments for respiration table.
COMMENT ON COLUMN garmin.respiration.user_id IS
'References garmin.user(user_id). Identifies which user '
'this respiration measurement belongs to.';
COMMENT ON COLUMN garmin.respiration.timestamp IS
'Timestamp of the respiration rate measurement.';
COMMENT ON COLUMN garmin.respiration.value IS
'Respiration rate value in breaths per minute.';
COMMENT ON COLUMN garmin.respiration.create_ts IS
'Timestamp when the record was created in the database.';

----------------------------------------------------------------------------------------

-- Intensity minutes table for storing daily intensity minute measurements.
CREATE TABLE IF NOT EXISTS garmin.intensity_minutes (
    user_id BIGINT REFERENCES garmin.user (user_id)
    , timestamp TIMESTAMPTZ
    , value FLOAT

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()

    -- Primary key.
    , PRIMARY KEY (user_id, timestamp)
);

-- Create indexes on intensity_minutes table.
CREATE INDEX IF NOT EXISTS intensity_minutes_user_id_idx
ON garmin.intensity_minutes (user_id);
CREATE INDEX IF NOT EXISTS intensity_minutes_timestamp_brin_idx
ON garmin.intensity_minutes USING brin (timestamp);
CREATE INDEX IF NOT EXISTS intensity_minutes_value_idx
ON garmin.intensity_minutes (value);

-- Table comment.
COMMENT ON TABLE garmin.intensity_minutes IS
'Intensity minutes measurements from Garmin devices tracking periods of moderate '
'to vigorous physical activity throughout the day at 15-minute intervals. Records are '
'available only when activity generating intensity is happening.';

-- Column comments for intensity_minutes table.
COMMENT ON COLUMN garmin.intensity_minutes.user_id IS
'References garmin.user(user_id). Identifies which user '
'this intensity minutes measurement belongs to.';
COMMENT ON COLUMN garmin.intensity_minutes.timestamp IS
'Timestamp of the intensity minutes measurement.';
COMMENT ON COLUMN garmin.intensity_minutes.value IS
'Intensity minutes value representing accumulated moderate to vigorous activity.';
COMMENT ON COLUMN garmin.intensity_minutes.create_ts IS
'Timestamp when the record was created in the database.';

----------------------------------------------------------------------------------------

-- Floors table for storing floors climbed measurements.
CREATE TABLE IF NOT EXISTS garmin.floors (
    user_id BIGINT REFERENCES garmin.user (user_id)
    , timestamp TIMESTAMPTZ
    , ascended INTEGER
    , descended INTEGER

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()

    -- Primary key.
    , PRIMARY KEY (user_id, timestamp)
);

-- Create indexes on floors table.
CREATE INDEX IF NOT EXISTS floors_user_id_idx
ON garmin.floors (user_id);
CREATE INDEX IF NOT EXISTS floors_timestamp_brin_idx
ON garmin.floors USING brin (timestamp);
CREATE INDEX IF NOT EXISTS floors_ascended_idx
ON garmin.floors (ascended);
CREATE INDEX IF NOT EXISTS floors_descended_idx
ON garmin.floors (descended);

-- Table comment.
COMMENT ON TABLE garmin.floors IS
'Floors climbed measurements from Garmin devices tracking floors ascended and '
'descended throughout the day at 15-minute intervals. Records are available only '
'when floor climbing activity is detected.';

-- Column comments for floors table.
COMMENT ON COLUMN garmin.floors.user_id IS
'References garmin.user(user_id). Identifies which user '
'this floors measurement belongs to.';
COMMENT ON COLUMN garmin.floors.timestamp IS
'Timestamp of the floors measurement (endTimeGMT from the data).';
COMMENT ON COLUMN garmin.floors.ascended IS
'Number of floors ascended during this measurement period.';
COMMENT ON COLUMN garmin.floors.descended IS
'Number of floors descended during this measurement period.';
COMMENT ON COLUMN garmin.floors.create_ts IS
'Timestamp when the record was created in the database.';

----------------------------------------------------------------------------------------
-- Personal Record table
----------------------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS garmin.personal_record (
    user_id BIGINT NOT NULL REFERENCES garmin.user (user_id)
    , activity_id BIGINT REFERENCES garmin.activity (activity_id)
    , timestamp TIMESTAMPTZ NOT NULL
    , type_id INTEGER NOT NULL
    , label TEXT
    , value FLOAT
    , latest BOOLEAN NOT NULL DEFAULT FALSE

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()

    -- Primary key (activity_id excluded to allow NULL values for steps records).
    , PRIMARY KEY (user_id, type_id, timestamp)
);

-- Indexes.
CREATE UNIQUE INDEX IF NOT EXISTS personal_record_user_id_type_id_latest_idx
ON garmin.personal_record (user_id, type_id) WHERE latest = TRUE;
CREATE INDEX IF NOT EXISTS garmin_personal_record_user_id_idx
ON garmin.personal_record (user_id);
CREATE INDEX IF NOT EXISTS garmin_personal_record_activity_id_idx
ON garmin.personal_record (activity_id);
CREATE INDEX IF NOT EXISTS garmin_personal_record_timestamp_idx
ON garmin.personal_record (timestamp);
CREATE INDEX IF NOT EXISTS garmin_personal_record_type_id_idx
ON garmin.personal_record (type_id);
CREATE INDEX IF NOT EXISTS garmin_personal_record_label_idx
ON garmin.personal_record (label);
CREATE INDEX IF NOT EXISTS garmin_personal_record_latest_idx
ON garmin.personal_record (latest);

-- Comments.
COMMENT ON TABLE garmin.personal_record IS
'Personal records achieved by users across various activity types and distances.';

COMMENT ON COLUMN garmin.personal_record.user_id IS
'Foreign key reference to the user profile.';
COMMENT ON COLUMN garmin.personal_record.activity_id IS
'Garmin activity ID where this personal record was achieved.';
COMMENT ON COLUMN garmin.personal_record.timestamp IS
'Timestamp when the personal record was achieved (prStartTimeGmt).';
COMMENT ON COLUMN garmin.personal_record.type_id IS
'Personal record type identifier (e.g., 1=Run 1km, 3=Run 5km, 7=Run Longest).';
COMMENT ON COLUMN garmin.personal_record.label IS
'Human-readable description of the personal record type.';
COMMENT ON COLUMN garmin.personal_record.value IS
'Value of the personal record (time in seconds for distances, distance in meters).';
COMMENT ON COLUMN garmin.personal_record.latest IS
'Boolean flag indicating whether this is the latest personal record for this user.';
COMMENT ON COLUMN garmin.personal_record.create_ts IS
'Timestamp when the record was created in the database.';

----------------------------------------------------------------------------------------

-- Race predictions table for storing predicted race times.
CREATE TABLE IF NOT EXISTS garmin.race_predictions (
    user_id BIGINT REFERENCES garmin.user (user_id)
    , date DATE
    , time_5k FLOAT
    , time_10k FLOAT
    , time_half_marathon FLOAT
    , time_marathon FLOAT
    , latest BOOLEAN NOT NULL DEFAULT FALSE

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()

    -- Primary key.
    , PRIMARY KEY (user_id, date)
);

-- Create unique index for latest flag.
CREATE UNIQUE INDEX IF NOT EXISTS race_predictions_user_id_latest_unique_idx
ON garmin.race_predictions (user_id) WHERE latest = TRUE;
CREATE INDEX IF NOT EXISTS race_predictions_user_id_idx
ON garmin.race_predictions (user_id);
CREATE INDEX IF NOT EXISTS race_predictions_date_idx
ON garmin.race_predictions (date);
CREATE INDEX IF NOT EXISTS race_predictions_latest_idx
ON garmin.race_predictions (latest);

-- Table comment.
COMMENT ON TABLE garmin.race_predictions IS
'Race time predictions from Garmin Connect including 5K, 10K, half marathon, '
'and marathon predicted times. The latest column indicates the most recent prediction.';

-- Column comments.
COMMENT ON COLUMN garmin.race_predictions.user_id IS
'References garmin.user(user_id). Identifies which user '
'this race prediction belongs to.';
COMMENT ON COLUMN garmin.race_predictions.date IS
'Calendar date of the race prediction.';
COMMENT ON COLUMN garmin.race_predictions.time_5k IS
'Predicted 5K race time in seconds.';
COMMENT ON COLUMN garmin.race_predictions.time_10k IS
'Predicted 10K race time in seconds.';
COMMENT ON COLUMN garmin.race_predictions.time_half_marathon IS
'Predicted half marathon race time in seconds.';
COMMENT ON COLUMN garmin.race_predictions.time_marathon IS
'Predicted marathon race time in seconds.';
COMMENT ON COLUMN garmin.race_predictions.latest IS
'Boolean flag indicating whether this is the latest race prediction for this user.';
COMMENT ON COLUMN garmin.race_predictions.create_ts IS
'Timestamp when the record was created in the database.';

----------------------------------------------------------------------------------------

-- Time-series metrics table for activity FIT file data.
CREATE TABLE IF NOT EXISTS garmin.activity_ts_metric (
    activity_id BIGINT REFERENCES garmin.activity (activity_id) ON DELETE CASCADE
    , timestamp TIMESTAMPTZ NOT NULL
    , name TEXT NOT NULL
    , value FLOAT
    , units TEXT

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes.
CREATE INDEX IF NOT EXISTS activity_ts_metric_activity_id_idx
ON garmin.activity_ts_metric (activity_id);
CREATE INDEX IF NOT EXISTS activity_ts_metric_timestamp_brin_idx
ON garmin.activity_ts_metric USING brin (timestamp);
CREATE INDEX IF NOT EXISTS activity_ts_metric_name_idx
ON garmin.activity_ts_metric (name);
CREATE INDEX IF NOT EXISTS activity_ts_metric_value_idx
ON garmin.activity_ts_metric (value);
CREATE INDEX IF NOT EXISTS activity_ts_metric_units_idx
ON garmin.activity_ts_metric (units);

-- Table comment.
COMMENT ON TABLE garmin.activity_ts_metric IS
'Time-series metrics extracted from activity FIT files including heart rate, '
'cadence, power, speed, distance, GPS coordinates, and other sensor measurements '
'recorded during activities. Each record represents a single measurement at a '
'specific point in time.';

-- Column comments.
COMMENT ON COLUMN garmin.activity_ts_metric.activity_id IS
'References garmin.activity(activity_id). Identifies which activity this '
'metric measurement belongs to.';
COMMENT ON COLUMN garmin.activity_ts_metric.timestamp IS
'Timestamp when the metric measurement was recorded.';
COMMENT ON COLUMN garmin.activity_ts_metric.name IS
'Name of the metric, which varies with activity type (e.g., heart_rate, cadence, '
'power, position_lat, position_log).';
COMMENT ON COLUMN garmin.activity_ts_metric.value IS
'Numeric value of the metric measurement.';
COMMENT ON COLUMN garmin.activity_ts_metric.units IS
'Units of measurement for the metric value (e.g., bpm, rpm, watts).';
COMMENT ON COLUMN garmin.activity_ts_metric.create_ts IS
'Timestamp when the record was created in the database.';

----------------------------------------------------------------------------------------

-- Activity split metrics table for FIT file split data.
CREATE TABLE IF NOT EXISTS garmin.activity_split_metric (
    activity_id BIGINT REFERENCES garmin.activity (activity_id) ON DELETE CASCADE
    , split_idx INTEGER NOT NULL
    , split_type TEXT
    , name TEXT NOT NULL
    , value FLOAT
    , units TEXT

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()

    -- Primary key.
    , PRIMARY KEY (activity_id, split_idx, name)
);

-- Indexes.
CREATE INDEX IF NOT EXISTS activity_split_metric_activity_id_idx
ON garmin.activity_split_metric (activity_id);
CREATE INDEX IF NOT EXISTS activity_split_metric_split_idx_idx
ON garmin.activity_split_metric (split_idx);
CREATE INDEX IF NOT EXISTS activity_split_metric_split_type_idx
ON garmin.activity_split_metric (split_type);
CREATE INDEX IF NOT EXISTS activity_split_metric_name_idx
ON garmin.activity_split_metric (name);
CREATE INDEX IF NOT EXISTS activity_split_metric_value_idx
ON garmin.activity_split_metric (value);
CREATE INDEX IF NOT EXISTS activity_split_metric_units_idx
ON garmin.activity_split_metric (units);

-- Table comment.
COMMENT ON TABLE garmin.activity_split_metric IS
'Split metrics extracted from activity FIT files representing Garmin''s algorithmic '
'breakdown of activities into intervals (e.g., run/walk detection, active intervals). '
'Each record represents a single metric for a specific split segment.';

-- Column comments.
COMMENT ON COLUMN garmin.activity_split_metric.activity_id IS
'References garmin.activity(activity_id). Identifies which activity this '
'split metric belongs to.';
COMMENT ON COLUMN garmin.activity_split_metric.split_idx IS
'Split index number starting from 1, incrementing for each split frame in the activity.';
COMMENT ON COLUMN garmin.activity_split_metric.split_type IS
'Type of split segment (e.g., rwd_run, rwd_walk, rwd_stand, interval_active).';
COMMENT ON COLUMN garmin.activity_split_metric.name IS
'Name of the metric (e.g., total_elapsed_time, total_distance, avg_speed).';
COMMENT ON COLUMN garmin.activity_split_metric.value IS
'Numeric value of the split metric measurement.';
COMMENT ON COLUMN garmin.activity_split_metric.units IS
'Units of measurement for the metric value (e.g., s, km, km/h).';
COMMENT ON COLUMN garmin.activity_split_metric.create_ts IS
'Timestamp when the record was created in the database.';

----------------------------------------------------------------------------------------

-- Activity lap metrics table for FIT file lap data.
CREATE TABLE IF NOT EXISTS garmin.activity_lap_metric (
    activity_id BIGINT REFERENCES garmin.activity (activity_id) ON DELETE CASCADE
    , lap_idx INTEGER NOT NULL
    , name TEXT NOT NULL
    , value FLOAT
    , units TEXT

    -- Audit fields.
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()

    -- Primary key.
    , PRIMARY KEY (activity_id, lap_idx, name)
);

-- Indexes.
CREATE INDEX IF NOT EXISTS activity_lap_metric_activity_id_idx
ON garmin.activity_lap_metric (activity_id);
CREATE INDEX IF NOT EXISTS activity_lap_metric_lap_idx_idx
ON garmin.activity_lap_metric (lap_idx);
CREATE INDEX IF NOT EXISTS activity_lap_metric_name_idx
ON garmin.activity_lap_metric (name);
CREATE INDEX IF NOT EXISTS activity_lap_metric_value_idx
ON garmin.activity_lap_metric (value);
CREATE INDEX IF NOT EXISTS activity_lap_metric_units_idx
ON garmin.activity_lap_metric (units);

-- Table comment.
COMMENT ON TABLE garmin.activity_lap_metric IS
'Lap metrics extracted from activity FIT files representing device-triggered '
'lap segments (manual button press, auto distance/time triggers). Each record '
'represents a single metric for a specific lap segment.';

-- Column comments.
COMMENT ON COLUMN garmin.activity_lap_metric.activity_id IS
'References garmin.activity(activity_id). Identifies which activity this '
'lap metric belongs to.';
COMMENT ON COLUMN garmin.activity_lap_metric.lap_idx IS
'Lap index number starting from 1, incrementing for each lap frame in the activity.';
COMMENT ON COLUMN garmin.activity_lap_metric.name IS
'Name of the metric (e.g., timestamp, start_time, total_elapsed_time, distance).';
COMMENT ON COLUMN garmin.activity_lap_metric.value IS
'Numeric value of the lap metric measurement.';
COMMENT ON COLUMN garmin.activity_lap_metric.units IS
'Units of measurement for the metric value (e.g., s, m, deg).';
COMMENT ON COLUMN garmin.activity_lap_metric.create_ts IS
'Timestamp when the record was created in the database.';

----------------------------------------------------------------------------------------
