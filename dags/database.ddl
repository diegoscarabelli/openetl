/*
========================================================================================
`LENS` DATABASE CREATION
========================================================================================
Description: This script creates the lens database for data pipeline operations.
             Must be executed before schemas.ddl, iam.sql, and pipeline table scripts.

Prerequisites:
  - PostgreSQL (or TimescaleDB-enabled PostgreSQL) must be installed and running
  - Must have superuser privileges (typically postgres user).

Connection:
  - Connect to the default `postgres` database to create the `lens` database:
    psql -U postgres -d postgres -f dags/database.ddl
  - Alternative with TCP/IP and password authentication:
    psql -h localhost -U postgres -d postgres -f dags/database.ddl

Notes:
  - Uses IF NOT EXISTS for idempotent execution (safe to run multiple times).
  - Character encoding and collation are set for UTF-8 support.
========================================================================================
*/

-- Set client encoding for consistent character handling.
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;

----------------------------------------------------------------------------------------
-- DATABASE CREATION
----------------------------------------------------------------------------------------

-- Note: IF NOT EXISTS requires PostgreSQL 9.5+
-- SQLFluff linter doesn't support this syntax, but PostgreSQL does.
-- noqa: disable=CP02
CREATE DATABASE IF NOT EXISTS lens
    WITH
    ENCODING = 'UTF8'
    LC_COLLATE = 'en_US.UTF-8'
    LC_CTYPE = 'en_US.UTF-8'
    TEMPLATE = template0;
-- noqa: enable=CP02

COMMENT ON DATABASE lens IS
    'Data pipeline analytics database.';
