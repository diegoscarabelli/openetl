/*
========================================================================================
SQL IDENTITY AND ACCESS MANAGEMENT (IAM) FOR AIRFLOW DATA PIPELINES AND SUPERSET
========================================================================================
Description:  This script creates users, roles, and permissions associated with
              Airflow data pipelines data processing and data visualization in Superset.
              Works in conjunction with database.ddl and schemas.ddl to establish a
              complete data pipeline access control system.

Prerequisites:
  - The lens database must exist (created by database.ddl).
  - Schemas must be created (created by schemas.ddl).
  - Must have superuser privileges (typically postgres user).
  - IMPORTANT: Replace all <REDACTED> password placeholders with actual passwords
    before running this script.
  - Re-running this script will fail if roles or users already exist; drop
    them first or skip this step.

Optional Components:
  - Superset roles and permissions (see SUPERSET ROLES AND PERMISSIONS section).
  - If not using Superset, comment out the entire Superset section before running.
  - Note: Running with Superset section will not cause errors, it will just create
    additional unused users and roles.

Naming Convention:
  - Airflow pipeline users follow the format: airflow_{dag_id}
    Example: For a DAG with id "garmin", the user is "airflow_garmin"
    This naming is automatically set in dags/lib/etl_config.py:
    self.postgres_user = f"airflow_{self.dag_id}"

Connection:
  - Connect to the lens database to create users and grant permissions:
    psql -U postgres -d lens -f dags/iam.sql
  - Alternative with TCP/IP and password authentication:
    psql -h localhost -U postgres -d lens -f dags/iam.sql
========================================================================================
*/


-- Set client encoding for consistent character handling.
SET client_encoding = 'UTF8';

-- Read-only access role for data consumers.
CREATE ROLE readers;

----------------------------------------------------------------------------------------
-- AIRFLOW SERVICE USERS
----------------------------------------------------------------------------------------

-- Airflow service user for Garmin data pipeline operations.
CREATE USER airflow_garmin
    WITH PASSWORD '<REDACTED>';
COMMENT ON ROLE airflow_garmin IS
    'Service user for Airflow Garmin data pipeline operations.';

-- Airflow service user for LinkedIn data pipeline operations.
CREATE USER airflow_linkedin
    WITH PASSWORD '<REDACTED>';
COMMENT ON ROLE airflow_linkedin IS
    'Service user for Airflow LinkedIn data pipeline operations.';

-- Airflow service user for WID data pipeline operations.
CREATE USER airflow_wid
    WITH PASSWORD '<REDACTED>';
COMMENT ON ROLE airflow_wid IS
    'Service user for Airflow WID data pipeline operations.';

-- Grant foundational read-only access to airflow users.
-- This provides base SELECT permissions across all schemas via the readers role.
GRANT readers TO airflow_garmin;
GRANT readers TO airflow_linkedin;
GRANT readers TO airflow_wid;

----------------------------------------------------------------------------------------
-- INFRASTRUCTURE MONITORING ROLE SETUP
----------------------------------------------------------------------------------------

-- Create specialized role for infrastructure monitoring operations.
CREATE ROLE infra_monitor_role;
COMMENT ON ROLE infra_monitor_role IS
    'Role for infrastructure monitoring data operations including metrics ingestion '
    'and alerting.';

-- Grant monitoring role to airflow users.
GRANT infra_monitor_role TO airflow_garmin;
GRANT infra_monitor_role TO airflow_linkedin;
GRANT infra_monitor_role TO airflow_wid;

-- Grant schema access and data manipulation permissions to monitoring role.
GRANT USAGE ON SCHEMA infra_monitor TO infra_monitor_role;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA infra_monitor
TO infra_monitor_role;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA infra_monitor
TO infra_monitor_role;

-- Set default privileges for future objects in monitoring schema.
ALTER DEFAULT PRIVILEGES IN SCHEMA infra_monitor
    GRANT SELECT, INSERT, UPDATE ON TABLES TO infra_monitor_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA infra_monitor
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO infra_monitor_role;

----------------------------------------------------------------------------------------
-- READ-ONLY ACCESS PERMISSIONS
----------------------------------------------------------------------------------------

-- Grant schema usage permissions to readers role.
GRANT USAGE ON SCHEMA garmin TO readers;
GRANT USAGE ON SCHEMA linkedin TO readers;
GRANT USAGE ON SCHEMA wid TO readers;
GRANT USAGE ON SCHEMA infra_monitor TO readers;
GRANT USAGE ON SCHEMA superset_uploads TO readers;

-- Grant SELECT permissions on existing tables and views.
GRANT SELECT ON ALL TABLES IN SCHEMA garmin TO readers;
GRANT SELECT ON ALL TABLES IN SCHEMA linkedin TO readers;
GRANT SELECT ON ALL TABLES IN SCHEMA wid TO readers;
GRANT SELECT ON ALL TABLES IN SCHEMA infra_monitor TO readers;
GRANT SELECT ON ALL TABLES IN SCHEMA superset_uploads TO readers;

-- Grant SELECT permissions on existing sequences.
GRANT SELECT ON ALL SEQUENCES IN SCHEMA garmin TO readers;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA linkedin TO readers;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA wid TO readers;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA infra_monitor TO readers;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA superset_uploads TO readers;

-- Set default privileges for future objects (ensures new tables are readable).
ALTER DEFAULT PRIVILEGES IN SCHEMA garmin
    GRANT SELECT ON TABLES TO readers;
ALTER DEFAULT PRIVILEGES IN SCHEMA linkedin
    GRANT SELECT ON TABLES TO readers;
ALTER DEFAULT PRIVILEGES IN SCHEMA wid
    GRANT SELECT ON TABLES TO readers;
ALTER DEFAULT PRIVILEGES IN SCHEMA infra_monitor
    GRANT SELECT ON TABLES TO readers;
ALTER DEFAULT PRIVILEGES IN SCHEMA superset_uploads
    GRANT SELECT ON TABLES TO readers;

ALTER DEFAULT PRIVILEGES IN SCHEMA garmin
    GRANT SELECT ON SEQUENCES TO readers;
ALTER DEFAULT PRIVILEGES IN SCHEMA linkedin
    GRANT SELECT ON SEQUENCES TO readers;
ALTER DEFAULT PRIVILEGES IN SCHEMA wid
    GRANT SELECT ON SEQUENCES TO readers;
ALTER DEFAULT PRIVILEGES IN SCHEMA infra_monitor
    GRANT SELECT ON SEQUENCES TO readers;
ALTER DEFAULT PRIVILEGES IN SCHEMA superset_uploads
    GRANT SELECT ON SEQUENCES TO readers;

----------------------------------------------------------------------------------------
-- AIRFLOW SERVICE USERS PERMISSIONS ON LENS DATABASE SCHEMAS
----------------------------------------------------------------------------------------

-- Grant data manipulation permissions to airflow_garmin for pipeline operations.
GRANT USAGE ON SCHEMA garmin TO airflow_garmin;
GRANT INSERT, UPDATE ON ALL TABLES IN SCHEMA garmin TO airflow_garmin;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA garmin TO airflow_garmin;

-- Grant DELETE on tables that use delete+insert instead of upsert.
GRANT DELETE ON garmin.strength_exercise TO airflow_garmin;
GRANT DELETE ON garmin.strength_set TO airflow_garmin;
GRANT DELETE ON garmin.activity_ts_metric TO airflow_garmin;
GRANT DELETE ON garmin.activity_split_metric TO airflow_garmin;
GRANT DELETE ON garmin.activity_lap_metric TO airflow_garmin;
GRANT DELETE ON garmin.activity_path TO airflow_garmin;
GRANT DELETE ON garmin.activity_hrv TO airflow_garmin;
GRANT DELETE ON garmin.swim_length TO airflow_garmin;
GRANT DELETE ON garmin.activity_event TO airflow_garmin;
-- menstrual_cycle_tag: delete-then-reinsert per (user_id, date) so user-removed
-- tags propagate. menstrual_cycle_summary: wipe-and-replace predicted_cycle=true
-- rows on each extract because Garmin's projection dates shift between runs.
GRANT DELETE ON garmin.menstrual_cycle_tag TO airflow_garmin;
GRANT DELETE ON garmin.menstrual_cycle_summary TO airflow_garmin;

-- Set default privileges for future objects in garmin schema.
ALTER DEFAULT PRIVILEGES IN SCHEMA garmin
    GRANT INSERT, UPDATE ON TABLES TO airflow_garmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA garmin
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO airflow_garmin;

-- Grant data manipulation permissions to airflow_linkedin for pipeline operations.
GRANT USAGE ON SCHEMA linkedin TO airflow_linkedin;
GRANT INSERT, UPDATE ON ALL TABLES IN SCHEMA linkedin TO airflow_linkedin;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA linkedin TO airflow_linkedin;

-- Set default privileges for future objects in linkedin schema.
ALTER DEFAULT PRIVILEGES IN SCHEMA linkedin
    GRANT INSERT, UPDATE ON TABLES TO airflow_linkedin;
ALTER DEFAULT PRIVILEGES IN SCHEMA linkedin
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO airflow_linkedin;

-- Grant data manipulation permissions to airflow_wid for pipeline operations.
-- REFERENCES lets it rebuild the observation foreign keys against the dimensions;
-- CREATE lets it rebuild the observation primary key and index (both create objects
-- in the wid schema) during finalize.
GRANT USAGE, CREATE ON SCHEMA wid TO airflow_wid;
GRANT INSERT, UPDATE, DELETE, REFERENCES ON ALL TABLES IN SCHEMA wid TO airflow_wid;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA wid TO airflow_wid;

-- Set default privileges for future objects in wid schema.
ALTER DEFAULT PRIVILEGES IN SCHEMA wid
    GRANT INSERT, UPDATE, DELETE, REFERENCES ON TABLES TO airflow_wid;
ALTER DEFAULT PRIVILEGES IN SCHEMA wid
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO airflow_wid;

-- The pipeline reloads observation in full each run: it drops the primary key and
-- foreign keys, truncates, bulk-loads unindexed, then rebuilds the constraints
-- (process.py prepare_observation_table / finalize_observation_table). ALTER and
-- TRUNCATE require ownership, so airflow_wid owns the observation fact table. (This
-- runs after tables.ddl has created the table.)
ALTER TABLE wid.observation OWNER TO airflow_wid;

----------------------------------------------------------------------------------------
-- SUPERSET ROLES AND PERMISSIONS (OPTIONAL)
----------------------------------------------------------------------------------------
-- Optional: Comment out this entire section if not using Apache Superset for data
-- visualization. Running with this section will not cause errors, it will just create
-- additional unused users and roles (superset_user, superset_upload_role).
----------------------------------------------------------------------------------------

-- Create user for Superset service
CREATE USER superset_user WITH PASSWORD '<REDACTED>';
GRANT readers TO superset_user;

-- Create role for Superset data upload operations.
CREATE ROLE superset_upload_role;
COMMENT ON ROLE superset_upload_role IS
    'Role for Apache Superset users to upload and manage ad-hoc datasets.';

-- Grant upload role to superset service user.
GRANT superset_upload_role TO superset_user;

-- Grant schema creation and table management permissions.
GRANT CREATE ON SCHEMA superset_uploads TO superset_upload_role;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA superset_uploads
TO superset_upload_role;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA superset_uploads
TO superset_upload_role;

-- Set default privileges for future objects in superset_uploads schema.
ALTER DEFAULT PRIVILEGES IN SCHEMA superset_uploads
    GRANT ALL PRIVILEGES ON TABLES TO superset_upload_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA superset_uploads
    GRANT ALL PRIVILEGES ON SEQUENCES TO superset_upload_role;

----------------------------------------------------------------------------------------
