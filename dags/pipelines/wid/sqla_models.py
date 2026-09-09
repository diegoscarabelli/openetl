"""
SQLAlchemy models for WID data processing and database interaction.

These models reflect the database tables defined in dags/pipelines/wid/tables.ddl.
"""

from sqlalchemy import (
    Boolean,
    Column,
    Computed,
    Float,
    MetaData,
    Numeric,
    SmallInteger,
    Text,
)

from dags.lib.sql_utils import fkey, make_base

# Shared metadata and base class with update_ts for upsert operations.
_shared_metadata = MetaData()

UpsertBase = make_base(schema="wid", include_update_ts=True, metadata=_shared_metadata)


class Country(UpsertBase):
    """
    WID entity dimension (countries and WID aggregate/region codes).
    """

    __tablename__ = "country"

    country_code = Column(Text, primary_key=True)
    name = Column(Text)
    region = Column(Text)


class Variable(UpsertBase):
    """
    WID variable dimension: one row per native variable code, code unpacked.
    """

    __tablename__ = "variable"

    variable_code = Column(Text, primary_key=True)
    series_type = Column(Text, nullable=False)
    concept = Column(Text, nullable=False)
    # Generated in the database from series_type and concept; never inserted.
    sixlet = Column(Text, Computed("series_type || concept", persisted=True))
    age_code = Column(Text, nullable=False)
    pop_code = Column(Text, nullable=False)
    short_name = Column(Text)
    description = Column(Text)
    technical_description = Column(Text)
    unit = Column(Text)
    long_type = Column(Text)
    long_pop = Column(Text)
    long_age = Column(Text)


class Percentile(UpsertBase):
    """
    WID percentile dimension: numeric bounds and width per percentile code.
    """

    __tablename__ = "percentile"

    percentile_code = Column(Text, primary_key=True)
    is_range = Column(Boolean, nullable=False)
    lower_bound = Column(Numeric, nullable=False)
    upper_bound = Column(Numeric, nullable=False)
    width = Column(Numeric, nullable=False)


class Provenance(UpsertBase):
    """
    Country-specific WID provenance (grain: country, variable).
    """

    __tablename__ = "provenance"

    country_code = Column(
        Text, fkey("wid", "country", "country_code"), primary_key=True
    )
    variable_code = Column(
        Text, fkey("wid", "variable", "variable_code"), primary_key=True
    )
    source = Column(Text)
    method = Column(Text)
    data_quality_score = Column(Float)


class Observation(UpsertBase):
    """
    WID observation fact table (one value per country, variable, percentile, and year).
    """

    __tablename__ = "observation"

    country_code = Column(
        Text, fkey("wid", "country", "country_code"), primary_key=True
    )
    variable_code = Column(
        Text, fkey("wid", "variable", "variable_code"), primary_key=True
    )
    percentile_code = Column(
        Text, fkey("wid", "percentile", "percentile_code"), primary_key=True
    )
    year = Column(SmallInteger, primary_key=True)
    value = Column(Numeric)
