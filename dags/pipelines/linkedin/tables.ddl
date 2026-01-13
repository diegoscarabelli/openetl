/*
========================================================================================
SQL RESOURCES FOR LINKEDIN DATA
========================================================================================
Description: This script creates database tables and other SQL resources for storing
             LinkedIn connection data.

Prerequisites:
  - The linkedin schema must already exist (created by schemas.ddl)
  - PostgreSQL must be running
  - Must have appropriate privileges

Connection:
  - Connect to the lens database to create tables:
    psql -U postgres -d lens -f dags/pipelines/linkedin/tables.ddl
========================================================================================
*/

-- Set client encoding and transaction isolation.
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;

----------------------------------------------------------------------------------------
-- LINKEDIN CONNECTION TABLE
----------------------------------------------------------------------------------------

-- Connections table containing LinkedIn connection data.
CREATE TABLE IF NOT EXISTS linkedin.connection (
    -- Record identification.
    connection_id SERIAL PRIMARY KEY

    -- Connection identity.
    , url TEXT NOT NULL UNIQUE
    , first_name TEXT
    , last_name TEXT
    , email_address TEXT

    -- Professional info.
    , company TEXT
    , position TEXT

    -- Connection metadata.
    , connected_on DATE
    , active_connection BOOLEAN NOT NULL DEFAULT TRUE

    -- Audit fields.
    , capture_date DATE NOT NULL
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
    , update_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for connection table.
CREATE INDEX IF NOT EXISTS connection_active_connection_idx
ON linkedin.connection (active_connection);
CREATE INDEX IF NOT EXISTS connection_connected_on_idx
ON linkedin.connection (connected_on);
CREATE INDEX IF NOT EXISTS connection_company_idx
ON linkedin.connection (company);
CREATE INDEX IF NOT EXISTS connection_create_ts_brin_idx
ON linkedin.connection USING brin (create_ts);

-- Table comment.
COMMENT ON TABLE linkedin.connection IS
'LinkedIn connection data imported from CSV exports. Tracks both current '
'and historical connections with active_connection flag indicating status.';

-- Column comments.
COMMENT ON COLUMN linkedin.connection.connection_id IS
'Auto-incrementing primary key for connection records.';
COMMENT ON COLUMN linkedin.connection.url IS
'LinkedIn profile URL - unique identifier for each connection.';
COMMENT ON COLUMN linkedin.connection.first_name IS
'First name of the connection.';
COMMENT ON COLUMN linkedin.connection.last_name IS
'Last name of the connection.';
COMMENT ON COLUMN linkedin.connection.email_address IS
'Email address of the connection (may be null if not shared).';
COMMENT ON COLUMN linkedin.connection.company IS
'Company/organization of the connection at time of export.';
COMMENT ON COLUMN linkedin.connection.position IS
'Job title/position of the connection at time of export.';
COMMENT ON COLUMN linkedin.connection.connected_on IS
'Date when the connection was established.';
COMMENT ON COLUMN linkedin.connection.active_connection IS
'Boolean flag indicating if this is an active connection. Set to FALSE '
'when connection is removed (present in DB but not in latest CSV export).';
COMMENT ON COLUMN linkedin.connection.capture_date IS
'Date when the data was captured/exported from LinkedIn (extracted from filename). '
'Used to ensure older exports do not overwrite newer data during out-of-order processing.';
COMMENT ON COLUMN linkedin.connection.create_ts IS
'Timestamp when the record was first created in the database.';
COMMENT ON COLUMN linkedin.connection.update_ts IS
'Timestamp when the record was last updated in the database.';

----------------------------------------------------------------------------------------
