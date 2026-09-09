"""
WID data processor for the ETL pipeline.

Implements the pure transform helpers, the WidProcessor class, and the prepare/finalize
steps that bracket the load. Each run is a full reload: prepare_observation_table drops
the observation primary key, foreign keys, and secondary index and truncates the table;
the parallel process tasks then append each country's observations into that unindexed
table (alongside upserting the country, variable, and provenance dimensions); and
finalize_observation_table rebuilds the constraints and index, which also validates the
load. Building the indexes once is far cheaper than maintaining them across ~141M
inserts. The global countries FileSet upserts country names and regions.
"""

import csv

from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from dags.lib.dag_utils import Processor
from dags.lib.filesystem_utils import FileSet
from dags.lib.logging_utils import LOGGER
from dags.lib.sql_utils import copy_records, get_lens_engine, upsert_model_instances
from dags.pipelines.wid.constants import WIDFileTypes
from dags.pipelines.wid.sqla_models import Country, Provenance, Variable

# Observation primary key and foreign keys, dropped before the load and rebuilt after
# it (see prepare_observation_table / finalize_observation_table). Loading into an
# unindexed table and building the composite key once is far faster than maintaining
# the index and checking the foreign keys on every one of ~141M inserts; the rebuild
# also validates the load (duplicates fail the PK, orphans fail the FKs). Names match
# the constraints declared in tables.ddl.
_OBSERVATION_CONSTRAINTS = {
    "observation_pkey": "PRIMARY KEY (country_code, variable_code, year)",
    "observation_country_code_fkey": (
        "FOREIGN KEY (country_code) REFERENCES wid.country (country_code)"
    ),
    "observation_variable_code_fkey": (
        "FOREIGN KEY (variable_code) REFERENCES wid.variable (fully_qualified_code)"
    ),
}

# Secondary index on observation, likewise dropped for the load and rebuilt after, so
# nothing is maintained per row during the bulk load. Name and definition match
# tables.ddl.
_OBSERVATION_INDEX_NAME = "wid_observation_variable_idx"
_OBSERVATION_INDEX_DDL = (
    f"CREATE INDEX {_OBSERVATION_INDEX_NAME} ON wid.observation "
    "(variable_code, year, country_code)"
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


def build_variable_code(variable: str, percentile: str, age: str, pop: str) -> str:
    """
    Build the fully qualified variable code from the WID data-CSV columns.

    The data CSV ``variable`` column is the packed ``sixlet + pop + age`` string; the
    fully qualified code is ``sixlet_percentile_age_pop``.

    :param variable: Packed variable string (e.g. "sptincj992").
    :param percentile: Percentile range code (e.g. "p99p100").
    :param age: Age-group code (e.g. "992").
    :param pop: Population-unit code (e.g. "j").
    :return: Fully qualified code (e.g. "sptinc_p99p100_992_j").
    """
    return f"{variable[:6]}_{percentile}_{age}_{pop}"


def variable_fields(
    variable: str, percentile: str, age: str, pop: str
) -> Dict[str, str]:
    """
    Build the unpacked variable-dimension fields for one code.

    :param variable: Packed variable string (sixlet + pop + age).
    :param percentile: Percentile range code.
    :param age: Age-group code.
    :param pop: Population-unit code.
    :return: Dict with fully_qualified_code, sixlet, series_type, concept, percentile,
        age_code, and pop_code.
    """
    sixlet = variable[:6]
    return {
        "fully_qualified_code": build_variable_code(variable, percentile, age, pop),
        "sixlet": sixlet,
        "series_type": sixlet[0],
        "concept": sixlet[1:],
        "percentile": percentile,
        "age_code": age,
        "pop_code": pop,
    }


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
    :return: Dict mapping (sixlet, age_code, pop_code) to a dict of concept-level fields
        plus country-specific provenance fields (source, method, data_quality_score,
        country).
    """
    result: Dict[Tuple[str, str, str], Dict[str, object]] = {}
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for row in reader:
            sixlet = row["variable"][:6]
            key = (sixlet, row["age"], row["pop"])
            result[key] = {
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


def iter_observations(path: Path) -> Iterator[Tuple[str, str, str, Optional[str]]]:
    """
    Stream observation rows as (country_code, variable_code, year, value) tuples.

    :param path: Path to the semicolon-delimited observation CSV.
    :return: Iterator of (country_code, variable_code, year, value) tuples aligned to
        the observation COPY columns; value is None when the source cell is empty.
    """
    with open(path, newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for row in reader:
            code = build_variable_code(
                row["variable"], row["percentile"], row["age"], row["pop"]
            )
            value = row["value"] if row["value"] != "" else None
            yield (row["country"], code, row["year"], value)


def build_variable_rows(
    path: Path, meta: Dict[Tuple[str, str, str], Dict[str, object]]
) -> List[Dict[str, Optional[str]]]:
    """
    Build distinct variable-dimension rows from an observation CSV plus metadata.

    The set of fully qualified codes comes from the observation CSV; the concept-level
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
            fields = variable_fields(
                row["variable"], row["percentile"], row["age"], row["pop"]
            )
            code = fields["fully_qualified_code"]
            if code in seen:
                continue
            seen.add(code)
            concept = meta.get(
                (fields["sixlet"], fields["age_code"], fields["pop_code"]), {}
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
        if variable_rows:
            # The variable dimension is global (keyed by fully_qualified_code, no
            # country) and its concept-level metadata is country-invariant, so the
            # first country to introduce a code sets its definition. Insert missing
            # codes and leave existing rows untouched (DO NOTHING): this avoids
            # re-updating shared codes once per country (~200 redundant writes and
            # update_ts bumps for common codes) and never overwrites a populated
            # row with a later country's NULLs.
            #
            # Insert in a deterministic order (by conflict key) so concurrent process
            # workers acquire the shared variable-index locks in the same order.
            # Without this, parallel per-country loads insert overlapping new codes in
            # different orders and PostgreSQL aborts one transaction with a deadlock,
            # quarantining that country.
            variable_rows.sort(key=lambda row: row["fully_qualified_code"])
            upsert_model_instances(
                session=session,
                model_instances=[Variable(**row) for row in variable_rows],
                conflict_columns=["fully_qualified_code"],
                on_conflict_update=False,
            )

        provenance = [
            Provenance(
                country_code=fields["country"] or country,
                sixlet=key[0],
                age_code=key[1],
                pop_code=key[2],
                source=fields["source"],
                method=fields["method"],
                data_quality_score=fields["data_quality_score"],
            )
            for key, fields in meta.items()
        ]
        if provenance:
            upsert_model_instances(
                session=session,
                model_instances=provenance,
                conflict_columns=["country_code", "sixlet", "age_code", "pop_code"],
                on_conflict_update=True,
                update_columns=["source", "method", "data_quality_score"],
            )

        # Full reload: prepare_observation_table truncated the (now unindexed)
        # observation table before this task, so just append this country's rows.
        written = copy_records(
            session,
            "wid.observation",
            ["country_code", "variable_code", "year", "value"],
            iter_observations(data_path),
        )
        LOGGER.info(f"Loaded {written} observations for {country}.")


def prepare_observation_table(sql_user: str, **context) -> None:
    """
    Drop the observation primary key and foreign keys and truncate it for a full reload.

    Runs once before the parallel process tasks so they append into an unindexed,
    constraint-free table (fast bulk load); finalize_observation_table rebuilds the
    constraints afterwards.

    :param sql_user: SQL user (credential file name) to connect as; must own the
        observation table so it can ALTER and TRUNCATE it.
    """
    engine = get_lens_engine(sql_user)
    with Session(engine) as session:
        session.execute(text(f"DROP INDEX IF EXISTS wid.{_OBSERVATION_INDEX_NAME}"))
        for name in _OBSERVATION_CONSTRAINTS:
            session.execute(
                text(f"ALTER TABLE wid.observation DROP CONSTRAINT IF EXISTS {name}")
            )
        session.execute(text("TRUNCATE wid.observation"))
        session.commit()
    LOGGER.info("Dropped observation constraints and index and truncated the table.")


def finalize_observation_table(sql_user: str, **context) -> None:
    """
    Rebuild the observation primary key and foreign keys after the load.

    Building the composite key once and validating the foreign keys in a single pass is
    far cheaper than maintaining them per row during the load, and it doubles as a load
    check: duplicate keys fail the primary key, orphaned codes fail the foreign keys.

    :param sql_user: SQL user (credential file name) to connect as; must own the
        observation table and hold REFERENCES on the country and variable tables.
    """
    engine = get_lens_engine(sql_user)
    with Session(engine) as session:
        # A larger maintenance_work_mem and parallel workers speed up the one-time
        # index builds (the primary key and secondary index dominate this step).
        session.execute(text("SET LOCAL maintenance_work_mem = '1GB'"))
        session.execute(text("SET LOCAL max_parallel_maintenance_workers = 4"))
        for name, definition in _OBSERVATION_CONSTRAINTS.items():
            session.execute(
                text(f"ALTER TABLE wid.observation ADD CONSTRAINT {name} {definition}")
            )
        session.execute(text(_OBSERVATION_INDEX_DDL))
        session.commit()
    LOGGER.info("Rebuilt observation primary key, foreign keys, and index.")
