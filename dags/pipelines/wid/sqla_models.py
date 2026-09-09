"""
SQLAlchemy models for WID data processing and database interaction.

These models reflect the database tables defined in dags/pipelines/wid/tables.ddl.
"""

from sqlalchemy import Column, Float, MetaData, Numeric, SmallInteger, Text

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
    WID variable dimension: one row per fully qualified code, code unpacked.
    """

    __tablename__ = "variable"

    fully_qualified_code = Column(Text, primary_key=True)
    sixlet = Column(Text, nullable=False)
    series_type = Column(Text, nullable=False)
    concept = Column(Text, nullable=False)
    age_code = Column(Text, nullable=False)
    pop_code = Column(Text, nullable=False)
    percentile = Column(Text, nullable=False)
    short_name = Column(Text)
    description = Column(Text)
    technical_description = Column(Text)
    unit = Column(Text)
    long_type = Column(Text)
    long_pop = Column(Text)
    long_age = Column(Text)


class Provenance(UpsertBase):
    """
    Country-specific WID provenance (grain: country, sixlet, age, pop).
    """

    __tablename__ = "provenance"

    country_code = Column(
        Text, fkey("wid", "country", "country_code"), primary_key=True
    )
    sixlet = Column(Text, primary_key=True)
    age_code = Column(Text, primary_key=True)
    pop_code = Column(Text, primary_key=True)
    source = Column(Text)
    method = Column(Text)
    data_quality_score = Column(Float)


class Observation(UpsertBase):
    """
    WID observation fact table (one value per country, variable, and year).
    """

    __tablename__ = "observation"

    country_code = Column(
        Text, fkey("wid", "country", "country_code"), primary_key=True
    )
    variable_code = Column(
        Text, fkey("wid", "variable", "fully_qualified_code"), primary_key=True
    )
    year = Column(SmallInteger, primary_key=True)
    value = Column(Numeric)
