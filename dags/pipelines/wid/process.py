"""
WID data processor for the ETL pipeline.

Implements the pure transform helpers, the WidProcessor class, and the prepare/finalize
steps that bracket the load. Each run is a full reload: prepare_observation_table drops
the observation primary key, foreign keys, and secondary index and truncates the table;
the parallel process tasks then append each country's observations into that unindexed
table (alongside upserting the country, variable, and provenance dimensions); and
finalize_observation_table completes the percentile dimension from the loaded facts and
rebuilds the constraints and index, which also validates the load. Building the indexes
once is far cheaper than maintaining them across ~141M inserts. The global countries
FileSet upserts country names and regions.

A time series is identified by (variable_code, percentile_code) and a single observation
by (country_code, variable_code, percentile_code, year): variable_code is WID's native
code (sixlet + pop + age, e.g. sptincj992) and percentile is its own dimension.
"""

import csv
import re

from decimal import Decimal
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from dags.lib.dag_utils import Processor
from dags.lib.filesystem_utils import FileSet
from dags.lib.logging_utils import LOGGER
from dags.lib.sql_utils import copy_records, get_lens_engine, upsert_model_instances
from dags.pipelines.wid.constants import WIDFileTypes
from dags.pipelines.wid.sqla_models import Country, Percentile, Provenance, Variable

# Observation primary key and foreign keys, dropped before the load and rebuilt after
# it (see prepare_observation_table / finalize_observation_table). Loading into an
# unindexed table and building the composite key once is far faster than maintaining
# the index and checking the foreign keys on every one of ~141M inserts; the rebuild
# also validates the load (duplicates fail the PK, orphans fail the FKs). Names match
# the constraints declared in tables.ddl.
_OBSERVATION_CONSTRAINTS = {
    "observation_pkey": (
        "PRIMARY KEY (country_code, variable_code, percentile_code, year)"
    ),
    "observation_country_code_fkey": (
        "FOREIGN KEY (country_code) REFERENCES wid.country (country_code)"
    ),
    "observation_variable_code_fkey": (
        "FOREIGN KEY (variable_code) REFERENCES wid.variable (variable_code)"
    ),
    "observation_percentile_code_fkey": (
        "FOREIGN KEY (percentile_code) REFERENCES wid.percentile (percentile_code)"
    ),
}

# Secondary index on observation, likewise dropped for the load and rebuilt after, so
# nothing is maintained per row during the bulk load. It serves whole-series lookups
# (a series is variable_code + percentile_code over years). Name and definition match
# tables.ddl.
_OBSERVATION_INDEX_NAME = "wid_observation_series_idx"
_OBSERVATION_INDEX_DDL = (
    f"CREATE INDEX {_OBSERVATION_INDEX_NAME} ON wid.observation "
    "(variable_code, percentile_code, year, country_code)"
)

# Concept-level variable fields sourced from the metadata CSV (same across countries).
_VARIABLE_META_FIELDS = [
    "short_name",
    "description",
    "technical_description",
    "unit",
    "long_type",
    "long_pop",
    "long_age",
]

# WID percentile codes: an explicit range (pXpY) or a single g-percentile point (pX),
# where X and Y may carry decimals (e.g. p99.9).
_PERCENTILE_RANGE_RE = re.compile(r"^p(\d+(?:\.\d+)?)p(\d+(?:\.\d+)?)$")
_PERCENTILE_POINT_RE = re.compile(r"^p(\d+(?:\.\d+)?)$")

# Upper bound of the top g-percentile point (the distribution runs to 100).
_PERCENTILE_MAX = Decimal(100)


def variable_fields(variable: str, age: str, pop: str) -> Dict[str, str]:
    """
    Build the unpacked variable-dimension fields for one native code.

    :param variable: Native variable code (sixlet + pop + age, e.g. "sptincj992").
    :param age: Age-group code.
    :param pop: Population-unit code.
    :return: Dict with variable_code, series_type, concept, age_code, and pop_code. The
        sixlet is generated in the database from series_type and concept.
    """
    sixlet = variable[:6]
    return {
        "variable_code": variable,
        "series_type": sixlet[0],
        "concept": sixlet[1:],
        "age_code": age,
        "pop_code": pop,
    }


def build_percentile_rows(codes: Iterable[str]) -> List[Dict[str, object]]:
    """
    Build percentile-dimension rows from a set of WID percentile codes.

    Two kinds of code occur. An explicit range ``pXpY`` maps to the bracket [X, Y];
    zero-width ranges (``pXpX``, e.g. ``p31p31``) are valid and denote a single
    percentile position (width 0). A g-percentile point ``pX`` (used by average series)
    maps to the group [X, next), whose upper bound is the next percentile point present
    in the data (the next g-percentile in a full load); the top point runs to 100.

    :param codes: Iterable of distinct WID percentile codes.
    :return: List of percentile-dimension row dicts (percentile_code, is_range,
        lower_bound, upper_bound, width).
    :raises ValueError: If a code matches neither the range nor the point pattern, or is
        inverted (upper < lower, which would violate the percentile CHECKs).
    """
    ranges: List[Tuple[str, Decimal, Decimal]] = []
    points: List[Tuple[str, Decimal]] = []
    for code in set(codes):
        range_match = _PERCENTILE_RANGE_RE.match(code)
        if range_match:
            lower = Decimal(range_match.group(1))
            upper = Decimal(range_match.group(2))
            if lower > upper:
                raise ValueError(
                    f"WID percentile range {code!r} is inverted "
                    f"(lower={lower}, upper={upper})."
                )
            ranges.append((code, lower, upper))
            continue
        point_match = _PERCENTILE_POINT_RE.match(code)
        if point_match:
            points.append((code, Decimal(point_match.group(1))))
            continue
        raise ValueError(f"Unrecognized WID percentile code: {code!r}.")

    rows: List[Dict[str, object]] = [
        {
            "percentile_code": code,
            "is_range": True,
            "lower_bound": lower,
            "upper_bound": upper,
            "width": upper - lower,
        }
        for code, lower, upper in ranges
    ]

    # Order the points so each one's upper bound is the next point's lower bound; the
    # top point runs to 100.
    points.sort(key=lambda item: item[1])
    for index, (code, lower) in enumerate(points):
        upper = points[index + 1][1] if index + 1 < len(points) else _PERCENTILE_MAX
        if upper < lower:
            raise ValueError(
                f"WID percentile point {code!r} is inverted "
                f"(lower={lower}, upper={upper})."
            )
        rows.append(
            {
                "percentile_code": code,
                "is_range": False,
                "lower_bound": lower,
                "upper_bound": upper,
                "width": upper - lower,
            }
        )
    return rows


def _to_float(value: Optional[str]) -> Optional[float]:
    """
    Parse a float, returning None for empty or unparseable values.

    :param value: String value to parse.
    :return: Float value, or None.
    """
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def parse_metadata(path: Path) -> Dict[Tuple[str, str, str], Dict[str, object]]:
    """
    Parse a WID_metadata CSV into a lookup keyed by (sixlet, age, pop).

    :param path: Path to the semicolon-delimited metadata CSV.
    :return: Dict mapping (sixlet, age_code, pop_code) to a dict of the native
        variable_code, concept-level fields, and country-specific provenance fields
        (source, method, data_quality_score, country).
    """
    result: Dict[Tuple[str, str, str], Dict[str, object]] = {}
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for row in reader:
            sixlet = row["variable"][:6]
            key = (sixlet, row["age"], row["pop"])
            result[key] = {
                # The metadata carries WID's native variable code verbatim; use it
                # directly rather than re-packing the split columns.
                "variable_code": row["variable"],
                "short_name": row.get("shortname") or None,
                "description": row.get("simpledes") or None,
                "technical_description": row.get("technicaldes") or None,
                "unit": row.get("unit") or None,
                "long_type": row.get("longtype") or None,
                "long_pop": row.get("longpop") or None,
                "long_age": row.get("longage") or None,
                "source": row.get("source") or None,
                "method": row.get("method") or None,
                "data_quality_score": _to_float(row.get("data_quality_score")),
                "country": row.get("country"),
            }
    return result


def parse_countries(path: Path) -> List[Dict[str, Optional[str]]]:
    """
    Parse the WID_countries CSV into country-dimension records.

    :param path: Path to the semicolon-delimited countries CSV.
    :return: List of dicts with country_code, name, and region.
    """
    records: List[Dict[str, Optional[str]]] = []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for row in reader:
            records.append(
                {
                    "country_code": row["alpha2"],
                    "name": row.get("titlename") or None,
                    "region": row.get("region") or None,
                }
            )
    return records


def first_country(path: Path) -> Optional[str]:
    """
    Return the country code from the first data row of an observation CSV.

    :param path: Path to the semicolon-delimited observation CSV.
    :return: Country code, or None if the file has no data rows.
    """
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for row in reader:
            return row["country"]
    return None


def iter_observations(
    path: Path,
) -> Iterator[Tuple[str, str, str, str, Optional[str]]]:
    """
    Stream observation rows as (country, variable, percentile, year, value) tuples.

    :param path: Path to the semicolon-delimited observation CSV.
    :return: Iterator of (country_code, variable_code, percentile_code, year, value)
        tuples aligned to the observation COPY columns; value is None when the source
        cell is empty.
    """
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for row in reader:
            value = row["value"] if row["value"] != "" else None
            yield (
                row["country"],
                row["variable"],
                row["percentile"],
                row["year"],
                value,
            )


def build_variable_rows(
    path: Path, meta: Dict[Tuple[str, str, str], Dict[str, object]]
) -> List[Dict[str, Optional[str]]]:
    """
    Build distinct variable-dimension rows from an observation CSV plus metadata.

    The set of native variable codes comes from the observation CSV; the concept-level
    text fields are attached from the metadata by (sixlet, age, pop).

    :param path: Path to the semicolon-delimited observation CSV.
    :param meta: Metadata lookup from parse_metadata.
    :return: List of variable-dimension row dicts.
    """
    seen = set()
    rows: List[Dict[str, Optional[str]]] = []
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for row in reader:
            fields = variable_fields(row["variable"], row["age"], row["pop"])
            code = fields["variable_code"]
            if code in seen:
                continue
            seen.add(code)
            concept = meta.get(
                (row["variable"][:6], fields["age_code"], fields["pop_code"]), {}
            )
            for field_name in _VARIABLE_META_FIELDS:
                fields[field_name] = concept.get(field_name)
            rows.append(fields)
    return rows


class WidProcessor(Processor):
    """
    Custom processor for WID observation and metadata CSV files.
    """

    def process_file_set(self, file_set: FileSet, session: Session) -> None:
        """
        Process one WID FileSet.

        A countries FileSet fills country names and regions. A country FileSet upserts
        the country, its variables, and its provenance, then appends its observations to
        the table truncated by prepare_observation_table.

        :param file_set: FileSet to process.
        :param session: SQLAlchemy Session object.
        """
        countries_files = file_set.get_files(WIDFileTypes.COUNTRIES)
        if countries_files:
            self._process_countries(countries_files[0], session)
            return

        data_files = file_set.get_files(WIDFileTypes.OBSERVATIONS)
        meta_files = file_set.get_files(WIDFileTypes.VARIABLE_METADATA)
        if not data_files:
            LOGGER.warning("WID FileSet has no observation file; skipping.")
            return
        meta_path = meta_files[0] if meta_files else None
        self._process_country(data_files[0], meta_path, session)

    def _process_countries(self, path: Path, session: Session) -> None:
        """
        Upsert the country dimension (names and regions) from the countries CSV.

        :param path: Path to the countries CSV.
        :param session: SQLAlchemy Session object.
        """
        instances = [Country(**record) for record in parse_countries(path)]
        LOGGER.info(f"Upserting {len(instances)} country records.")
        if instances:
            upsert_model_instances(
                session=session,
                model_instances=instances,
                conflict_columns=["country_code"],
                on_conflict_update=True,
                update_columns=["name", "region"],
            )

    def _process_country(
        self, data_path: Path, meta_path: Optional[Path], session: Session
    ) -> None:
        """
        Load one country: upsert country, variables, and provenance, then append its
        observations to the truncated, unindexed observation table.

        :param data_path: Path to the country's observation CSV.
        :param meta_path: Path to the country's metadata CSV, if present.
        :param session: SQLAlchemy Session object.
        """
        country = first_country(data_path)
        if country is None:
            LOGGER.warning(f"No data rows in {data_path.name}; skipping.")
            return
        LOGGER.info(f"Processing WID country {country} from {data_path.name}.")

        # The WID bulk export pairs each country's data file with a metadata file, so
        # meta is normally populated. Warn if it is missing: with first-writer-wins
        # variable upserts, any new codes this country introduces would be stored with
        # empty concept metadata.
        if meta_path is None:
            LOGGER.warning(
                f"No metadata file for country {country}; new variable codes will "
                "be stored with empty concept metadata."
            )
        meta = parse_metadata(meta_path) if meta_path else {}

        # Ensure the country row exists (code only) so observation/provenance FKs hold,
        # regardless of whether the countries FileSet has been processed yet.
        upsert_model_instances(
            session=session,
            model_instances=[Country(country_code=country)],
            conflict_columns=["country_code"],
            on_conflict_update=False,
        )

        variable_rows = build_variable_rows(data_path, meta)
        present_codes = {row["variable_code"] for row in variable_rows}
        if variable_rows:
            # The variable dimension is global (keyed by variable_code, no country) and
            # its concept-level metadata is country-invariant, so the first country to
            # introduce a code sets its definition. Insert missing codes and leave
            # existing rows untouched (DO NOTHING): this avoids re-updating shared codes
            # once per country (~200 redundant writes and update_ts bumps for common
            # codes) and never overwrites a populated row with a later country's NULLs.
            #
            # Insert in a deterministic order (by conflict key) so concurrent process
            # workers acquire the shared variable-index locks in the same order. Without
            # this, parallel per-country loads insert overlapping new codes in different
            # orders and PostgreSQL aborts one transaction with a deadlock, quarantining
            # that country.
            variable_rows.sort(key=lambda row: row["variable_code"])
            upsert_model_instances(
                session=session,
                model_instances=[Variable(**row) for row in variable_rows],
                conflict_columns=["variable_code"],
                on_conflict_update=False,
            )

        # Provenance is keyed by (country, variable). Emit a row only for variables this
        # country actually has data for, so the provenance -> variable foreign key holds
        # even when the metadata file lists variables absent from the data file.
        provenance = []
        for fields in meta.values():
            variable_code = fields["variable_code"]
            if variable_code not in present_codes:
                continue
            provenance.append(
                Provenance(
                    country_code=fields["country"] or country,
                    variable_code=variable_code,
                    source=fields["source"],
                    method=fields["method"],
                    data_quality_score=fields["data_quality_score"],
                )
            )
        if provenance:
            upsert_model_instances(
                session=session,
                model_instances=provenance,
                conflict_columns=["country_code", "variable_code"],
                on_conflict_update=True,
                update_columns=["source", "method", "data_quality_score"],
            )

        # Full reload: prepare_observation_table truncated the (now unindexed)
        # observation table before this task, so just append this country's rows.
        written = copy_records(
            session,
            "wid.observation",
            ["country_code", "variable_code", "percentile_code", "year", "value"],
            iter_observations(data_path),
        )
        LOGGER.info(f"Loaded {written} observations for {country}.")


def prepare_observation_table(sql_user: str, **context) -> None:
    """
    Reset the observation and percentile tables for a full reload.

    Drops the observation primary key, foreign keys, and index and truncates it, so the
    parallel process tasks append into an unindexed, constraint-free table (fast bulk
    load); finalize_observation_table rebuilds the constraints afterwards. Also clears
    the percentile dimension so its data-derived bounds reflect only the current load
    (finalize repopulates it). Percentile is emptied with DELETE, not TRUNCATE, because
    airflow_wid holds DELETE but not ownership of that table.

    :param sql_user: SQL user (credential file name) to connect as; must own the
        observation table so it can ALTER and TRUNCATE it, and hold DELETE on
        percentile.
    """
    engine = get_lens_engine(sql_user)
    with Session(engine) as session:
        session.execute(text(f"DROP INDEX IF EXISTS wid.{_OBSERVATION_INDEX_NAME}"))
        for name in _OBSERVATION_CONSTRAINTS:
            session.execute(
                text(f"ALTER TABLE wid.observation DROP CONSTRAINT IF EXISTS {name}")
            )
        session.execute(text("TRUNCATE wid.observation"))
        # The observation -> percentile foreign key is dropped above and observation is
        # truncated, so no rows reference percentile when it is cleared.
        session.execute(text("DELETE FROM wid.percentile"))
        session.commit()
    LOGGER.info(
        "Dropped observation constraints and index, truncated observations, and "
        "cleared the percentile dimension."
    )


def _populate_percentile_dimension(session: Session) -> None:
    """
    Upsert the percentile dimension from the percentile codes present in observations.

    Runs after the load (percentile codes are read from the loaded fact table) and
    before the observation foreign keys are rebuilt, so every referenced code exists.
    The point-code upper bounds need the full set of codes, which the loaded table
    provides in one place.

    :param session: SQLAlchemy Session whose transaction the upsert joins.
    """
    result = session.execute(
        text("SELECT DISTINCT percentile_code FROM wid.observation")
    )
    rows = build_percentile_rows([row[0] for row in result])
    if not rows:
        return
    upsert_model_instances(
        session=session,
        model_instances=[Percentile(**row) for row in rows],
        conflict_columns=["percentile_code"],
        on_conflict_update=True,
        update_columns=["is_range", "lower_bound", "upper_bound", "width"],
    )
    LOGGER.info(f"Populated the percentile dimension with {len(rows)} codes.")


def finalize_observation_table(sql_user: str, **context) -> None:
    """
    Complete the percentile dimension and rebuild the observation constraints.

    First populates the percentile dimension from the loaded observations, then rebuilds
    the observation primary key, foreign keys, and index. Building the composite key
    once and validating the foreign keys in a single pass is far cheaper than
    maintaining them per row during the load, and it doubles as a load check: duplicate
    keys fail the primary key, orphaned codes fail the foreign keys.

    :param sql_user: SQL user (credential file name) to connect as; must own the
        observation table and hold REFERENCES on the country, variable, and percentile
        tables.
    """
    engine = get_lens_engine(sql_user)
    with Session(engine) as session:
        # A larger maintenance_work_mem and parallel workers speed up the one-time
        # index builds (the primary key and secondary index dominate this step).
        session.execute(text("SET LOCAL maintenance_work_mem = '1GB'"))
        session.execute(text("SET LOCAL max_parallel_maintenance_workers = 4"))
        _populate_percentile_dimension(session)
        for name, definition in _OBSERVATION_CONSTRAINTS.items():
            session.execute(
                text(f"ALTER TABLE wid.observation ADD CONSTRAINT {name} {definition}")
            )
        session.execute(text(_OBSERVATION_INDEX_DDL))
        session.commit()
    LOGGER.info("Rebuilt observation primary key, foreign keys, and index.")
