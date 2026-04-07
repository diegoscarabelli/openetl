/*
========================================================================================
POSTGIS RESOURCES FOR GARMIN DATA
========================================================================================
Description: This script creates PostGIS-dependent tables and indexes for the
             Garmin pipeline. Run only if the PostGIS extension is installed in
             the `lens` database (see `dags/schemas.ddl`).
========================================================================================
*/

----------------------------------------------------------------------------------------

-- Country boundaries for reverse-geocoding activity coordinates to ISO codes.
-- Data source: Natural Earth 110m Admin 0 Countries (public domain).
-- One-time load via shp2pgsql:
--   wget https://naciscdn.org/naturalearth/110m/cultural/ne_110m_admin_0_countries.zip
--   unzip ne_110m_admin_0_countries.zip -d ne_countries
--   shp2pgsql -s 4326 ne_countries/ne_110m_admin_0_countries.shp public.countries_tmp \
--     | psql -U postgres -d lens
--   INSERT INTO garmin.countries (iso_a2, iso_a3, name, name_long, geom)
--     SELECT iso_a2, iso_a3, name, name_long, geom FROM public.countries_tmp;
--   DROP TABLE public.countries_tmp;
CREATE TABLE IF NOT EXISTS garmin.countries (
    country_id SERIAL PRIMARY KEY
    , iso_a2 TEXT
    , iso_a3 TEXT
    , name TEXT NOT NULL
    , name_long TEXT
    , geom GEOMETRY (MULTIPOLYGON, 4326) NOT NULL
);

-- Spatial index for ST_Contains lookups.
CREATE INDEX IF NOT EXISTS countries_geom_idx
ON garmin.countries USING gist (geom);

-- Table comment.
COMMENT ON TABLE garmin.countries IS
'Country boundaries from Natural Earth 110m for reverse-geocoding activity '
'locations to ISO country codes. Enables Superset World Map visualizations.';

-- Column comments.
COMMENT ON COLUMN garmin.countries.country_id IS
'Auto-generated primary key.';
COMMENT ON COLUMN garmin.countries.iso_a2 IS
'2-letter ISO 3166-1 country code.';
COMMENT ON COLUMN garmin.countries.iso_a3 IS
'3-letter ISO 3166-1 country code.';
COMMENT ON COLUMN garmin.countries.name IS
'Short country name.';
COMMENT ON COLUMN garmin.countries.name_long IS
'Long-form country name from Natural Earth name_long attribute.';
COMMENT ON COLUMN garmin.countries.geom IS
'Country boundary polygon (SRID 4326, WGS84).';

----------------------------------------------------------------------------------------
