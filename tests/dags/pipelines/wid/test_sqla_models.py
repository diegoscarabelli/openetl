"""
Tests for the WID SQLAlchemy models.

Verifies that the ORM models match the tables defined in tables.ddl (names, schema, key
columns, and primary keys).
"""

from dags.pipelines.wid import sqla_models as m


def test_table_names() -> None:
    """
    Each model maps to its expected table name.
    """
    assert m.Country.__tablename__ == "country"
    assert m.Variable.__tablename__ == "variable"
    assert m.Provenance.__tablename__ == "provenance"
    assert m.Observation.__tablename__ == "observation"


def test_schema_is_wid() -> None:
    """
    Models live in the wid schema.
    """
    assert m.Observation.__table__.schema == "wid"
    assert m.Variable.__table__.schema == "wid"


def test_observation_columns_and_pk() -> None:
    """
    Observation has the expected columns and composite primary key.
    """
    cols = set(m.Observation.__table__.columns.keys())
    assert {"country_code", "variable_code", "year", "value"} <= cols
    pk = {c.name for c in m.Observation.__table__.primary_key.columns}
    assert pk == {"country_code", "variable_code", "year"}


def test_variable_concept_and_long_fields() -> None:
    """
    Variable carries the concept-level and long-label fields, keyed by code.
    """
    cols = set(m.Variable.__table__.columns.keys())
    assert {
        "short_name",
        "description",
        "technical_description",
        "unit",
        "long_type",
        "long_pop",
        "long_age",
    } <= cols
    assert m.Variable.__table__.columns["fully_qualified_code"].primary_key


def test_provenance_pk() -> None:
    """
    Provenance is keyed by (country_code, sixlet, age_code, pop_code).
    """
    pk = {c.name for c in m.Provenance.__table__.primary_key.columns}
    assert pk == {"country_code", "sixlet", "age_code", "pop_code"}
