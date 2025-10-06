/*
========================================================================================
AIRFLOW METADATA DATABASE CREATION
========================================================================================
Description: This script creates the Airflow metadata database (`airflow_db`) and the
             `airflow` user for Airflow application operations. Also creates a read-only
             `readers` role and restricts backend control functions.
             After running this script, run airflow_db_grants.ddl to set up permissions
             within the `airflow_db` database.

Prerequisites:
  - PostgreSQL must be installed and running.
  - Must have superuser privileges (typically `postgres` user).
  - IMPORTANT: Replace <REDACTED> password placeholder with actual password before
    running this script.

Connection:
  - Connect to the default `postgres` database to create the `airflow_db` database:
    psql -U postgres -d postgres -f airflow_db.ddl
  - Alternative with TCP/IP and password authentication:
    psql -h localhost -U postgres -d postgres -f airflow_db.ddl

Next Steps:
  - After running this script, execute airflow_db_grants.ddl to configure permissions
    within the airflow_db database
========================================================================================
*/

-- Set client encoding for consistent character handling.
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;

----------------------------------------------------------------------------------------
-- SECURITY CONFIGURATION
----------------------------------------------------------------------------------------

-- Revoke permissions from all users except postgres.
REVOKE ALL ON FUNCTION pg_cancel_backend FROM public;
REVOKE ALL ON FUNCTION pg_terminate_backend FROM public;

-- Create read-only role for analytics.
CREATE ROLE IF NOT EXISTS readers;

----------------------------------------------------------------------------------------
-- AIRFLOW METADATA DATABASE AND USER
----------------------------------------------------------------------------------------

CREATE DATABASE airflow_db;
CREATE USER IF NOT EXISTS airflow WITH PASSWORD '<REDACTED>';
GRANT ALL PRIVILEGES ON DATABASE airflow_db TO airflow;

----------------------------------------------------------------------------------------