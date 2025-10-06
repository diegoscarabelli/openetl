/*
========================================================================================
AIRFLOW METADATA DATABASE PERMISSIONS
========================================================================================
Description: This script configures permissions within the `airflow_db` database for the
             `airflow` user and `readers` role. Must be executed after airflow_db.ddl.

Prerequisites:
  - The `airflow_db` database must exist (created by airflow_db.ddl).
  - The `airflow` user must exist (created by airflow_db.ddl).
  - The `readers` role must exist (created by airflow_db.ddl).
  - Must have superuser privileges (typically `postgres` user).

Connection:
  - Connect to the `airflow_db` database to configure permissions:
    psql -U postgres -d airflow_db -f airflow_db_grants.ddl
  - Alternative with TCP/IP and password authentication:
    psql -h localhost -U postgres -d airflow_db -f airflow_db_grants.ddl
========================================================================================
*/

-- Set client encoding for consistent character handling.
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;

----------------------------------------------------------------------------------------
-- AIRFLOW USER PERMISSIONS
----------------------------------------------------------------------------------------

-- Grant full privileges on public schema to airflow user.
GRANT ALL ON SCHEMA public TO airflow;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO airflow;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO airflow;

-- Set default privileges for future objects created by airflow user.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO airflow;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO airflow;

----------------------------------------------------------------------------------------
-- READ-ONLY PERMISSIONS FOR ANALYTICS
----------------------------------------------------------------------------------------

-- Grant read-only permissions to the readers role on the public schema.
GRANT USAGE ON SCHEMA public TO readers;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO readers;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO readers;

-- Set default privileges for future objects (ensures new tables are readable).
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO readers;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON SEQUENCES TO readers;

----------------------------------------------------------------------------------------
