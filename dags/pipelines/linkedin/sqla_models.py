"""
SQLAlchemy models for LinkedIn connection data processing and database interaction.

These models reflect database tables for storing LinkedIn connection data defined in the
tables.ddl file.
"""

from sqlalchemy import Boolean, Column, Date, Integer, MetaData, Text

from dags.lib.sql_utils import make_base


# Create shared metadata and base class with update_ts for upsert operations.
_shared_metadata = MetaData()

UpsertBase = make_base(
    schema="linkedin", include_update_ts=True, metadata=_shared_metadata
)


class Connection(UpsertBase):
    """
    LinkedIn connection record.

    Contains connection identity, professional information, and connection metadata. The
    url field serves as the unique business key for upsert operations.
    """

    __tablename__ = "connection"

    # Record identification.
    connection_id = Column(Integer, primary_key=True)

    # Connection identity.
    url = Column(Text, nullable=False, unique=True)
    first_name = Column(Text)
    last_name = Column(Text)
    email_address = Column(Text)

    # Professional info.
    company = Column(Text)
    position = Column(Text)

    # Connection metadata.
    connected_on = Column(Date)
    active_connection = Column(Boolean, nullable=False, default=True)
