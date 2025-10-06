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
  - Must have superuser privileges (typically postgres user)..
  - IMPORTANT: Replace all <REDACTED> password placeholders with actual passwords
    before running this script

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
CREATE ROLE IF NOT EXISTS readers;

----------------------------------------------------------------------------------------
-- AIRFLOW SERVICE USERS
----------------------------------------------------------------------------------------

-- Airflow service user for Garmin data pipeline operations.
CREATE USER IF NOT EXISTS airflow_garmin
    WITH PASSWORD '<REDACTED>';
COMMENT ON ROLE airflow_garmin IS
    'Service user for Airflow Garmin data pipeline operations.';

-- Grant foundational read-only access to airflow user.
-- This provides base SELECT permissions across all schemas via the readers role.
GRANT readers TO airflow_garmin;

----------------------------------------------------------------------------------------
-- INFRASTRUCTURE MONITORING ROLE SETUP
----------------------------------------------------------------------------------------

-- Create specialized role for infrastructure monitoring operations.
CREATE ROLE IF NOT EXISTS infra_monitor_role;
COMMENT ON ROLE infra_monitor_role IS
    'Role for infrastructure monitoring data operations including metrics ingestion '
    'and alerting.';

-- Grant monitoring role to airflow users.
GRANT infra_monitor_role TO airflow_garmin;

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
GRANT USAGE ON SCHEMA infra_monitor TO readers;
GRANT USAGE ON SCHEMA superset_uploads TO readers;

-- Grant SELECT permissions on existing tables and views.
GRANT SELECT ON ALL TABLES IN SCHEMA garmin TO readers;
GRANT SELECT ON ALL TABLES IN SCHEMA infra_monitor TO readers;
GRANT SELECT ON ALL TABLES IN SCHEMA superset_uploads TO readers;

-- Grant SELECT permissions on existing sequences.
GRANT SELECT ON ALL SEQUENCES IN SCHEMA garmin TO readers;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA infra_monitor TO readers;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA superset_uploads TO readers;

-- Set default privileges for future objects (ensures new tables are readable).
ALTER DEFAULT PRIVILEGES IN SCHEMA garmin 
    GRANT SELECT ON TABLES TO readers;
ALTER DEFAULT PRIVILEGES IN SCHEMA infra_monitor 
    GRANT SELECT ON TABLES TO readers;
ALTER DEFAULT PRIVILEGES IN SCHEMA superset_uploads 
    GRANT SELECT ON TABLES TO readers;

ALTER DEFAULT PRIVILEGES IN SCHEMA garmin 
    GRANT SELECT ON SEQUENCES TO readers;
ALTER DEFAULT PRIVILEGES IN SCHEMA infra_monitor 
    GRANT SELECT ON SEQUENCES TO readers;
ALTER DEFAULT PRIVILEGES IN SCHEMA superset_uploads 
    GRANT SELECT ON SEQUENCES TO readers;

----------------------------------------------------------------------------------------
-- AIRFLOW SERVICE USERS PERMISSIONS ON LENS DATABASE SCHEMAS
----------------------------------------------------------------------------------------

-- Grant data manipulation permissions to airflow_garmin for pipeline operations.
GRANT INSERT, UPDATE ON ALL TABLES IN SCHEMA garmin TO airflow_garmin;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA garmin TO airflow_garmin;

-- Set default privileges for future objects in garmin schema.
ALTER DEFAULT PRIVILEGES IN SCHEMA garmin 
    GRANT INSERT, UPDATE ON TABLES TO airflow_garmin;
ALTER DEFAULT PRIVILEGES IN SCHEMA garmin 
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO airflow_garmin;

----------------------------------------------------------------------------------------
-- SUPERSET ROLES AND PERMISSIONS (OPTIONAL)
----------------------------------------------------------------------------------------
-- Optional: Comment out this entire section if not using Apache Superset for data
-- visualization. Running with this section will not cause errors, it will just create
-- additional unused users and roles (superset_user, superset_upload_role).
----------------------------------------------------------------------------------------

-- Create user for Superset service
CREATE USER IF NOT EXISTS superset_user WITH PASSWORD '<REDACTED>';
GRANT readers TO superset_user;

-- Create role for Superset data upload operations.
CREATE ROLE IF NOT EXISTS superset_upload_role;
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