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
    assert m.Percentile.__tablename__ == "percentile"
    assert m.Provenance.__tablename__ == "provenance"
    assert m.Observation.__tablename__ == "observation"


def test_schema_is_wid() -> None:
    """
    Models live in the wid schema.
    """
    assert m.Observation.__table__.schema == "wid"
    assert m.Variable.__table__.schema == "wid"
    assert m.Percentile.__table__.schema == "wid"


def test_observation_columns_and_pk() -> None:
    """
    Observation has the expected columns and composite primary key (with percentile).
    """
    cols = set(m.Observation.__table__.columns.keys())
    assert {"country_code", "variable_code", "percentile_code", "year", "value"} <= cols
    pk = {c.name for c in m.Observation.__table__.primary_key.columns}
    assert pk == {"country_code", "variable_code", "percentile_code", "year"}


def test_variable_keyed_by_native_code() -> None:
    """
    Variable is keyed by the native variable_code and carries the metadata fields.
    """
    assert m.Variable.__table__.columns["variable_code"].primary_key
    cols = set(m.Variable.__table__.columns.keys())
    assert {
        "series_type",
        "concept",
        "sixlet",
        "age_code",
        "pop_code",
        "short_name",
        "description",
        "technical_description",
        "unit",
        "long_type",
        "long_pop",
        "long_age",
    } <= cols
    # Percentile is no longer part of the variable dimension.
    assert "percentile" not in cols


def test_variable_sixlet_is_generated() -> None:
    """
    Sixlet is a database-generated column (series_type || concept), never inserted.
    """
    assert m.Variable.__table__.columns["sixlet"].computed is not None


def test_percentile_columns_and_pk() -> None:
    """
    Percentile is keyed by percentile_code and carries bounds and the range flag.
    """
    pk = {c.name for c in m.Percentile.__table__.primary_key.columns}
    assert pk == {"percentile_code"}
    cols = set(m.Percentile.__table__.columns.keys())
    assert {"is_range", "lower_bound", "upper_bound", "width"} <= cols


def test_provenance_pk() -> None:
    """
    Provenance is keyed by (country_code, variable_code).
    """
    pk = {c.name for c in m.Provenance.__table__.primary_key.columns}
    assert pk == {"country_code", "variable_code"}
