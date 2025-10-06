/*
========================================================================================
`LENS` DATABASE SCHEMA INITIALIZATION
========================================================================================
Description: This script creates PostgreSQL extensions and schemas for the `lens`
             database. Must be executed after database.ddl and before iam.sql.

Prerequisites:
  - The `lens` database must already exist (created by database.ddl)
  - PostgreSQL must be running
  - Must have superuser privileges (typically `postgres` user)

Optional Components:
  - PostgreSQL extensions (see POSTGRESQL EXTENSIONS section).
  - If not installed, comment out the corresponding CREATE EXTENSION statements.
  - Note: Running with uninstalled extensions will cause errors.
  - Extensions included with PostgreSQL:
    * pg_stat_statements: SQL performance tracking.
  - Extensions requiring separate installation:
    * pgvectorscale: Vector similarity search.
    * TimescaleDB: Time-series database capabilities.

Connection:
  - Connect to the lens database to create extensions and schemas:
    psql -U postgres -d lens -f dags/schemas.ddl
  - Alternative with TCP/IP and password authentication:
    psql -h localhost -U postgres -d lens -f dags/schemas.ddl
========================================================================================
*/

-- Set client encoding and transaction isolation.
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;

----------------------------------------------------------------------------------------
-- POSTGRESQL EXTENSIONS (OPTIONAL)
----------------------------------------------------------------------------------------
-- Optional: Comment out CREATE EXTENSION statements for extensions not installed.
-- Note: Creating uninstalled extensions will cause errors and halt execution.
-- Extensions requiring separate installation: pgvectorscale, TimescaleDB
----------------------------------------------------------------------------------------

CREATE EXTENSION IF NOT EXISTS pg_stat_statements
    WITH SCHEMA public;
COMMENT ON EXTENSION pg_stat_statements IS
    'Track execution statistics of all SQL statements executed.';

CREATE EXTENSION IF NOT EXISTS vectorscale CASCADE;
COMMENT ON EXTENSION vectorscale IS 
    'High-performance vector similarity search for PostgreSQL.';

CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;
COMMENT ON EXTENSION timescaledb IS 
    'Time-series database built on PostgreSQL.';

----------------------------------------------------------------------------------------
-- SCHEMA CREATION AND CONFIGURATION
----------------------------------------------------------------------------------------

-- Garmin Connect data schema.
CREATE SCHEMA IF NOT EXISTS garmin;
COMMENT ON SCHEMA garmin IS 
    'Wellness, health, fitness and activities data from Garmin Connect platform.';

-- System monitoring schema.
CREATE SCHEMA IF NOT EXISTS infra_monitor;
COMMENT ON SCHEMA infra_monitor IS 
    'Infrastructure monitoring and alerting data including system metrics, 
     application logs, performance indicators, and alert configurations.';

-- User upload schema for Superset.
CREATE SCHEMA IF NOT EXISTS superset_uploads;
COMMENT ON SCHEMA superset_uploads IS 
    'Temporary storage for user-uploaded datasets through Apache Superset.';

-- Configure search path (public schema must be first for namespace access to
-- TimescaleDB functionality).
SET search_path TO
    public
    , garmin
    , infra_monitor
    , superset_uploads;

----------------------------------------------------------------------------------------
