/*
========================================================================================
SQL RESOURCES FOR WID (WORLD INEQUALITY DATABASE) DATA
========================================================================================
Description: This script creates database tables for storing the complete World
             Inequality Database (WID) dataset as a star schema in the wid schema:
             the observation fact table plus the country, variable, and provenance
             dimensions.

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

-- Variable dimension: unpacks the fully qualified code and holds concept-level,
-- country-independent metadata.
CREATE TABLE IF NOT EXISTS wid.variable (
    fully_qualified_code TEXT PRIMARY KEY
    , sixlet TEXT NOT NULL
    , series_type TEXT NOT NULL
    , concept TEXT NOT NULL
    , age_code TEXT NOT NULL
    , pop_code TEXT NOT NULL
    , percentile TEXT NOT NULL
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
'WID variable dimension: one row per fully qualified code, with the code unpacked.';
COMMENT ON COLUMN wid.variable.fully_qualified_code IS
'Fully qualified WID variable code (sixlet_percentile_age_pop). Primary key.';
COMMENT ON COLUMN wid.variable.sixlet IS 'Six-letter concept and series-type prefix.';
COMMENT ON COLUMN wid.variable.series_type IS
'One-letter series type (first letter of the sixlet; s=share, a=average, etc).';
COMMENT ON COLUMN wid.variable.concept IS
'Five-letter concept identifier (sixlet without the series-type letter).';
COMMENT ON COLUMN wid.variable.age_code IS 'Three-digit age-group code (e.g. 992).';
COMMENT ON COLUMN wid.variable.pop_code IS
'One-letter population-unit code (e.g. j=equal-split adults, i=individuals).';
COMMENT ON COLUMN wid.variable.percentile IS 'Percentile range code (e.g. p0p100).';
COMMENT ON COLUMN wid.variable.short_name IS 'Human-readable short name (shortname).';
COMMENT ON COLUMN wid.variable.description IS 'Plain-English description (simpledes).';
COMMENT ON COLUMN wid.variable.technical_description IS
'Technical methodology description (technicaldes).';
COMMENT ON COLUMN wid.variable.unit IS 'Value unit.';
COMMENT ON COLUMN wid.variable.long_type IS 'Long description of the series type.';
COMMENT ON COLUMN wid.variable.long_pop IS 'Long description of the population unit.';
COMMENT ON COLUMN wid.variable.long_age IS 'Long description of the age group.';

----------------------------------------------------------------------------------------
-- PROVENANCE DIMENSION
----------------------------------------------------------------------------------------

-- Country-specific provenance metadata. Grain is (country, sixlet, age, pop): WID
-- provides source/method/quality once per that tuple, not per percentile.
CREATE TABLE IF NOT EXISTS wid.provenance (
    country_code TEXT NOT NULL REFERENCES wid.country (country_code)
    , sixlet TEXT NOT NULL
    , age_code TEXT NOT NULL
    , pop_code TEXT NOT NULL
    , source TEXT
    , method TEXT
    , data_quality_score DOUBLE PRECISION
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
    , update_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
    , PRIMARY KEY (country_code, sixlet, age_code, pop_code)
);

COMMENT ON TABLE wid.provenance IS
'Country-specific WID variable provenance: source, method, and data-quality score.';
COMMENT ON COLUMN wid.provenance.country_code IS
'WID entity code. Part of the primary key. Foreign key to wid.country.';
COMMENT ON COLUMN wid.provenance.sixlet IS 'Six-letter concept and series-type prefix.';
COMMENT ON COLUMN wid.provenance.age_code IS 'Three-digit age-group code.';
COMMENT ON COLUMN wid.provenance.pop_code IS 'One-letter population-unit code.';
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
CREATE TABLE IF NOT EXISTS wid.observation (
    country_code TEXT NOT NULL REFERENCES wid.country (country_code)
    , variable_code TEXT NOT NULL REFERENCES wid.variable (fully_qualified_code)
    , year SMALLINT NOT NULL
    , value NUMERIC
    , create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
    , update_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
    , PRIMARY KEY (country_code, variable_code, year)
);

CREATE INDEX IF NOT EXISTS wid_observation_variable_idx
ON wid.observation (variable_code, year, country_code);

COMMENT ON TABLE wid.observation IS
'WID fact table: one value per country, variable, and year (~141M rows).';
COMMENT ON COLUMN wid.observation.country_code IS
'WID entity code. Part of the primary key. Foreign key to wid.country.';
COMMENT ON COLUMN wid.observation.variable_code IS
'Fully qualified variable code. Part of the primary key. FK to wid.variable.';
COMMENT ON COLUMN wid.observation.year IS 'Calendar year. Part of the primary key.';
COMMENT ON COLUMN wid.observation.value IS 'Numeric value (share, threshold, etc).';

----------------------------------------------------------------------------------------
