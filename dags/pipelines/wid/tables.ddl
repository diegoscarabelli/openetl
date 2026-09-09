/*
========================================================================================
SQL RESOURCES FOR WID (WORLD INEQUALITY DATABASE) DATA
========================================================================================
Description: This script creates database tables for storing the complete World
             Inequality Database (WID) dataset as a star schema in the wid schema:
             the observation fact table plus the country, variable, percentile, and
             provenance dimensions. A time series is identified by (variable_code,
             percentile_code); a single observation by
             (country_code, variable_code, percentile_code, year).

Prerequisites:
  - The wid schema must already exist (created by schemas.ddl).
  - PostgreSQL must be running.
  - Must have appropriate privileges.

Connection:
  - Connect to the lens database to create tables:
    psql -U postgres -d lens -f dags/pipelines/wid/tables.ddl
========================================================================================
*/

-- Set client encoding and standard string handling.
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;

----------------------------------------------------------------------------------------
-- COUNTRY DIMENSION
----------------------------------------------------------------------------------------

-- Country and entity dimension (real countries plus WID regional/world aggregates).
CREATE TABLE IF NOT EXISTS wid.country (
    country_code TEXT PRIMARY KEY
    , name TEXT
    , region TEXT
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
    , update_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE wid.country IS
'WID entity dimension: two-letter country codes and WID-specific aggregate codes.';
COMMENT ON COLUMN wid.country.country_code IS
'WID entity code (two-letter ISO-like code, or a WID aggregate/region code).';
COMMENT ON COLUMN wid.country.name IS 'Entity name (from WID_countries.csv titlename).';
COMMENT ON COLUMN wid.country.region IS 'Geographical region grouping.';

----------------------------------------------------------------------------------------
-- VARIABLE DIMENSION
----------------------------------------------------------------------------------------

-- Variable dimension, keyed by WID's native variable code (sixlet + pop + age, e.g.
-- sptincj992), with the code unpacked into its components and concept-level, country-
-- independent metadata attached. Percentile is NOT part of this dimension: it is its own
-- dimension and a column on the fact table.
CREATE TABLE IF NOT EXISTS wid.variable (
    variable_code TEXT PRIMARY KEY
    , series_type TEXT NOT NULL
    , concept TEXT NOT NULL
    , sixlet TEXT GENERATED ALWAYS AS (series_type || concept) STORED
    , age_code TEXT NOT NULL
    , pop_code TEXT NOT NULL
    , short_name TEXT
    , description TEXT
    , technical_description TEXT
    , unit TEXT
    , long_type TEXT
    , long_pop TEXT
    , long_age TEXT
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
    , update_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS wid_variable_sixlet_idx ON wid.variable (sixlet);
CREATE INDEX IF NOT EXISTS wid_variable_concept_idx ON wid.variable (concept);

COMMENT ON TABLE wid.variable IS
'WID variable dimension: one row per native variable code, with the code unpacked.';
COMMENT ON COLUMN wid.variable.variable_code IS
'WID native variable code (sixlet + pop + age, e.g. sptincj992). Primary key.';
COMMENT ON COLUMN wid.variable.series_type IS
'One-letter series type (first letter of the sixlet; s=share, a=average, etc).';
COMMENT ON COLUMN wid.variable.concept IS
'Five-letter concept identifier (sixlet without the series-type letter).';
COMMENT ON COLUMN wid.variable.sixlet IS
'Six-letter series-type and concept prefix (series_type || concept), generated.';
COMMENT ON COLUMN wid.variable.age_code IS 'Three-digit age-group code (e.g. 992).';
COMMENT ON COLUMN wid.variable.pop_code IS
'One-letter population-unit code (e.g. j=equal-split adults, i=individuals).';
COMMENT ON COLUMN wid.variable.short_name IS 'Human-readable short name (shortname).';
COMMENT ON COLUMN wid.variable.description IS 'Plain-English description (simpledes).';
COMMENT ON COLUMN wid.variable.technical_description IS
'Technical methodology description (technicaldes).';
COMMENT ON COLUMN wid.variable.unit IS 'Value unit.';
COMMENT ON COLUMN wid.variable.long_type IS 'Long description of the series type.';
COMMENT ON COLUMN wid.variable.long_pop IS 'Long description of the population unit.';
COMMENT ON COLUMN wid.variable.long_age IS 'Long description of the age group.';

----------------------------------------------------------------------------------------
-- PERCENTILE DIMENSION
----------------------------------------------------------------------------------------

-- Percentile dimension: one row per distinct percentile code, parsed into numeric
-- bounds. Two kinds of code occur: explicit ranges (e.g. p99p100 -> [99, 100], a
-- bracket; zero-width p31p31 -> a single position) and WID g-percentile points used by
-- average series (e.g. p99 -> the g-percentile group [99, 99.1), whose upper bound is
-- the next percentile point present in the data, which is the next g-percentile in a
-- full load). Populated by finalize_observation_table from the distinct codes present
-- in the loaded observations.
CREATE TABLE IF NOT EXISTS wid.percentile (
    percentile_code TEXT PRIMARY KEY
    , is_range BOOLEAN NOT NULL
    , lower_bound NUMERIC NOT NULL
    , upper_bound NUMERIC NOT NULL
    , width NUMERIC NOT NULL
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
    , update_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
    , CONSTRAINT percentile_bounds_check CHECK (upper_bound >= lower_bound)
    , CONSTRAINT percentile_width_check CHECK (width >= 0)
);

COMMENT ON TABLE wid.percentile IS
'WID percentile dimension: numeric bounds and width per percentile code.';
COMMENT ON COLUMN wid.percentile.percentile_code IS
'WID percentile code (range e.g. p99p100, or g-percentile point e.g. p99). Primary key.';
COMMENT ON COLUMN wid.percentile.is_range IS
'True for an explicit range bracket (pXpY); false for a g-percentile point (pX).';
COMMENT ON COLUMN wid.percentile.lower_bound IS 'Inclusive lower percentile bound.';
COMMENT ON COLUMN wid.percentile.upper_bound IS
'Upper percentile bound (range upper edge, or next present point for a point code).';
COMMENT ON COLUMN wid.percentile.width IS
'Bound width (upper_bound - lower_bound; 0 for a single-position code).';

----------------------------------------------------------------------------------------
-- PROVENANCE DIMENSION
----------------------------------------------------------------------------------------

-- Country-specific provenance metadata, keyed by (country, variable). WID provides
-- source/method/quality once per (country, variable), invariant across percentile.
CREATE TABLE IF NOT EXISTS wid.provenance (
    country_code TEXT NOT NULL
    , variable_code TEXT NOT NULL
    , source TEXT
    , method TEXT
    , data_quality_score DOUBLE PRECISION
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
    , update_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
    , CONSTRAINT provenance_pkey PRIMARY KEY (country_code, variable_code)
    , CONSTRAINT provenance_country_code_fkey FOREIGN KEY (country_code)
    REFERENCES wid.country (country_code)
    , CONSTRAINT provenance_variable_code_fkey FOREIGN KEY (variable_code)
    REFERENCES wid.variable (variable_code)
);

COMMENT ON TABLE wid.provenance IS
'Country-specific WID variable provenance: source, method, and data-quality score.';
COMMENT ON COLUMN wid.provenance.country_code IS
'WID entity code. Part of the primary key. Foreign key to wid.country.';
COMMENT ON COLUMN wid.provenance.variable_code IS
'WID native variable code. Part of the primary key. Foreign key to wid.variable.';
COMMENT ON COLUMN wid.provenance.source IS 'Country-specific data source citation.';
COMMENT ON COLUMN wid.provenance.method IS 'Country-specific methodology note.';
COMMENT ON COLUMN wid.provenance.data_quality_score IS
'Country-specific data-quality score for the variable.';

----------------------------------------------------------------------------------------
-- OBSERVATION FACT TABLE
----------------------------------------------------------------------------------------

-- Observation fact table (~141M rows). Plain PostgreSQL table (no hypertable): WID is
-- replaced in full on each annual release, which does not fit the append-only model
-- TimescaleDB compression optimizes for.
-- The primary key, foreign keys, and secondary index are named explicitly so the
-- pipeline can drop them before a bulk load and rebuild them afterwards (see process.py
-- prepare_observation_table / finalize_observation_table).
CREATE TABLE IF NOT EXISTS wid.observation (
    country_code TEXT NOT NULL
    , variable_code TEXT NOT NULL
    , percentile_code TEXT NOT NULL
    , year SMALLINT NOT NULL
    , value NUMERIC
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
    , update_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
    , CONSTRAINT observation_pkey
    PRIMARY KEY (country_code, variable_code, percentile_code, year)
    , CONSTRAINT observation_country_code_fkey FOREIGN KEY (country_code)
    REFERENCES wid.country (country_code)
    , CONSTRAINT observation_variable_code_fkey FOREIGN KEY (variable_code)
    REFERENCES wid.variable (variable_code)
    , CONSTRAINT observation_percentile_code_fkey FOREIGN KEY (percentile_code)
    REFERENCES wid.percentile (percentile_code)
);

CREATE INDEX IF NOT EXISTS wid_observation_series_idx
ON wid.observation (variable_code, percentile_code, year, country_code);

COMMENT ON TABLE wid.observation IS
'WID fact table: one value per country, variable, percentile, and year (~141M rows).';
COMMENT ON COLUMN wid.observation.country_code IS
'WID entity code. Part of the primary key. Foreign key to wid.country.';
COMMENT ON COLUMN wid.observation.variable_code IS
'WID native variable code. Part of the primary key. Foreign key to wid.variable.';
COMMENT ON COLUMN wid.observation.percentile_code IS
'WID percentile code. Part of the primary key. Foreign key to wid.percentile.';
COMMENT ON COLUMN wid.observation.year IS 'Calendar year. Part of the primary key.';
COMMENT ON COLUMN wid.observation.value IS 'Numeric value (share, threshold, etc).';

----------------------------------------------------------------------------------------
-- OWNERSHIP
----------------------------------------------------------------------------------------

-- airflow_wid must own the observation fact table so the pipeline can drop and rebuild
-- its primary key, foreign keys, and index and truncate it for a full reload
-- (process.py prepare_observation_table / finalize_observation_table). The airflow_wid
-- role is created earlier by iam.sql per the documented database-init order.
ALTER TABLE wid.observation OWNER TO airflow_wid;
