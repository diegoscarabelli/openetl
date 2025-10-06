"""
Database utilities for working with SQLAlchemy ORM models and PostgreSQL databases.

This module provides comprehensive database interaction capabilities including
engine and session creation, custom ORM base classes, bulk operations, and
credential management. It includes:
    - Engine and session creation for PostgreSQL databases.
    - Custom SQLAlchemy ORM base classes with timestamp columns.
    - Bulk upsert operations for efficient data loading.
    - Credential management for Airflow SQL users.
    - Query type enumeration for upsert logic.
    - Connection utilities for local and production environments.
"""

import json
import os
import socket
import urllib.parse

from datetime import datetime, timezone
from typing import List, Optional, Type, Dict, Any

from sqlalchemy import Column, create_engine, DateTime, ForeignKey, MetaData
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.sql import and_, or_
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeMeta, declarative_base
from sqlalchemy.orm import Session

from dags.lib.logging_utils import LOGGER


# Enum for query types used in upsert logic
class QueryType:
    """
    Enumeration of query types for upsert operations.
    """

    UPSERT = "upsert"
    INSERT = "insert"
    INSERT_IGNORE = "insert_ignore"


def make_base(
    schema: Optional[str] = None,
    include_update_ts: bool = False,
    metadata: Optional[MetaData] = None,
) -> Type[DeclarativeMeta]:
    """
    Create a custom base class for SQLAlchemy ORM models representing SQL database
    tables.

    :param schema: Schema name for the SQL database table.
    :param include_update_ts: Whether to include an update timestamp column.
    :param metadata: SQLAlchemy MetaData instance to share across models.
    :return: Declarative base class for ORM models.
    """

    metadata = metadata or MetaData()
    Base = declarative_base(metadata=metadata)

    class CustomBase(Base):
        """
        Custom SQLAlchemy ORM base class with optional schema and timestamp columns.
        """

        __abstract__ = True
        create_ts = Column(
            DateTime(timezone=True),
            default=datetime.now,
            nullable=False,
        )
        if include_update_ts:
            update_ts = Column(
                DateTime(timezone=True),
                default=datetime.now,
                onupdate=datetime.now,
                nullable=False,
            )

    if schema:
        CustomBase.__table_args__ = {"schema": schema}
    return CustomBase


def fkey(schema: str, table_name: str, column_name: str = None) -> ForeignKey:
    """
    Generate a ForeignKey object for a table in the specified schema.

    :param schema: Schema name.
    :param table_name: Foreign Table name.
    :param column_name: Foreign column name, defaults to <table_name>_id.
    :return: ForeignKey object.
    """

    return ForeignKey(".".join([schema, table_name, column_name or f"{table_name}_id"]))


def get_engine(
    host: str,
    username: str,
    password: str = None,
    db_name: str = None,
    protocol: str = "postgresql",
    execution_options: dict = None,
    echo: bool = False,
) -> Engine:
    """
    Obtain a SQLAlchemy engine instance for connecting to a SQL database using the
    provided connection string.

    :param host: IP address/DNS name of the server hosting the SQL database.
    :param username: Username for the SQL database.
    :param password: Password for the SQL database.
    :param db_name: SQL database name.
    :param protocol: Protocol to use for the connection.
    :param execution_options: Engine execution options.
    :param echo: Whether to print queries to stdout.
    :return: SQLAlchemy engine for database operations.
    """

    # Escape password as described in SQLAlchemy documentation:
    # https://docs.sqlalchemy.org/en/20/core/engines.html#escaping-special-characters
    password = ":" + urllib.parse.quote_plus(password) if password else ""

    if execution_options is None:
        execution_options = {"isolation_level": "READ COMMITTED"}

    return create_engine(
        f"{protocol}://{username}{password}@{host}/{db_name}",
        execution_options=execution_options,
        echo=echo,
        future=True,
    )


def _get_default_docker_host() -> str:
    """
    Determine the default Docker host address for connecting from a container.

    This function assumes the database is running on the same host machine where
    Docker/Airflow is running. It automatically detects the appropriate host
    address to connect from inside a container to services on the host.

    Tries to resolve host.docker.internal first (available on Docker Desktop).
    Falls back to 172.17.0.1 (Docker bridge network gateway on Linux) if
    host.docker.internal is not resolvable.

    Note: This assumption can be overridden by setting the SQL_DB_HOST
    environment variable to point to a different host (e.g., a remote database
    server).

    :return: Docker host address (either host.docker.internal or 172.17.0.1).
    """

    try:
        # Try to resolve host.docker.internal.
        socket.gethostbyname("host.docker.internal")
        return "host.docker.internal"
    except socket.gaierror:
        # host.docker.internal not available, use Docker bridge IP.
        return "172.17.0.1"


def get_lens_engine(user: str, echo: bool = False) -> Engine:
    """
    Obtain a SQLAlchemy engine for the `lens` PostgreSQL database.

    Connection parameters sourced from environment variables and credentials:
    - Credentials loaded from <user>.json in SQL_CREDENTIALS_DIR (required).
      Credential files are JSON with the following structure:
      {"user": "username", "password": "password"}
    - Host set via SQL_DB_HOST or auto-detected. Attempts to resolve
      "host.docker.internal", which works on Docker Desktop (Mac/Windows).
      Falls back to "172.17.0.1" (Docker bridge gateway on Linux)
      if host.docker.internal is not resolvable.
    - Uses PostgreSQL protocol.

    :param user: SQL database user corresponding to a credential file.
    :param echo: If True, logs all SQL statements.
    :return: SQLAlchemy engine for lens database operations.
    :raises RuntimeError: If SQL_CREDENTIALS_DIR not set or credential file
        missing.
    """

    sql_credentials_dir = os.getenv("SQL_CREDENTIALS_DIR")
    if not sql_credentials_dir:
        raise RuntimeError(
            "SQL_CREDENTIALS_DIR environment variable is not set. "
            "Please set it to the directory containing credential JSON files."
        )

    # Expand user home directory (~) in the path.
    sql_credentials_dir = os.path.expanduser(sql_credentials_dir)
    cred_path = os.path.join(sql_credentials_dir, f"{user}.json")
    if not os.path.exists(cred_path):
        raise RuntimeError(f"Credential file not found: {cred_path}.")
    with open(cred_path, "r", encoding="utf-8") as f:
        credentials = json.load(f)

    # If the user in the credentials file does not match the requested user,
    # log a warning and use the requested user.
    if credentials["user"] != user:
        LOGGER.warning(
            f"Credential file user '{credentials['user']}' does not match "
            f"requested user '{user}'. Using requested user."
        )
        credentials["user"] = user

    # Get the lens database host.
    db_host = os.getenv("SQL_DB_HOST") or _get_default_docker_host()

    return get_engine(
        host=db_host,
        username=credentials["user"],
        password=credentials["password"],
        db_name="lens",
        protocol="postgresql",
        echo=echo,
    )


def upsert_model_instances(
    session: Session,
    model_instances: List[DeclarativeMeta],
    update_columns: Optional[List[str]] = None,
    conflict_columns: Optional[List[str]] = None,
    on_conflict_update: bool = False,
    latest_check_column: str = None,
) -> List[DeclarativeMeta]:
    """
    Bulk upsert SQLAlchemy ORM model instances into SQL database tables, handling
    conflicts and optionally updating existing rows. This function converts model
    instances to dictionaries, delegates the upsert logic to a lower-level helper, and
    returns the persisted instances as they exist in the database after the operation.

    :param session: SQLAlchemy ORM session for database operations.
    :param model_instances: List of SQLAlchemy ORM model instances to upsert. All
        instances must be of the same model type representing a SQL database table.
    :param update_columns: List of columns to update in case of conflict. If None, all
        columns except the conflict columns will be updated.
    :param conflict_columns: List of columns to check for conflicts (e.g., primary
        key(s) or unique constraints). If None, a simple insert is performed and
        database conflicts may occur.
    :param on_conflict_update: If True, update rows on conflict; if False, ignore
        conflicts and do not update existing rows.
    :param latest_check_column: If specified, only update rows where the value in this
        column is greater than the existing value. Useful for time/version-based
        updates.
    :return: List of SQLAlchemy model instances as persisted in the database after
        upsert.
    """

    if not model_instances:
        raise ValueError("`model_instances` list cannot be empty.")
    model = model_instances[0].__class__
    if not all(isinstance(model_instance, model) for model_instance in model_instances):
        raise TypeError(
            f"All `model_instances` must be of the same type: {model.__name__}."
        )

    model_columns = model.__table__.columns.keys()
    values = []
    for instance in model_instances:
        instance_dict = {}
        for key, value in instance.__dict__.items():
            if key in model_columns:
                instance_dict[key] = value
        values.append(instance_dict)
    results = _upsert_values(
        model=model,
        values=values,
        session=session,
        update_columns=update_columns,
        conflict_columns=conflict_columns,
        on_conflict_update=on_conflict_update,
        latest_check_column=latest_check_column,
        returning_columns=model_columns,
    )

    persisted_instances = [model(**result) for result in results]

    return persisted_instances


def _upsert_values(
    model: Type[Type[DeclarativeMeta]],
    values: List[dict],
    session: Session,
    update_columns: Optional[List[str]] = None,
    conflict_columns: Optional[List[str]] = None,
    on_conflict_update: bool = False,
    latest_check_column: str = None,
    returning_columns: Optional[List[str]] = None,
) -> Optional[List[Dict[str, Any]]]:
    """
    Bulk upsert dictionaries of values into SQL database tables using SQLAlchemy ORM
    models and sessions, supporting conflict resolution and conditional updates. This
    function builds and executes the appropriate SQL statement for insert, upsert, or
    insert-ignore, and can return the resulting rows as dictionaries if requested.

    :param model: SQLAlchemy ORM model class representing a SQL database table.
    :param values: List of dictionaries containing the data to upsert. Each dictionary
        should map SQL database column names to values.
    :param session: SQLAlchemy ORM session for database operations.
    :param update_columns: List of columns to update in case of conflict. If None, all
        columns except the conflict columns will be updated.
    :param conflict_columns: List of columns to check for conflicts (e.g., primary
        key(s) or unique constraints). If None, a simple insert is performed and
        database conflicts may occur.
    :param on_conflict_update: If True, update rows on conflict; if False, ignore
        conflicts and do not update existing rows.
    :param latest_check_column: If specified, only update rows where the value in this
        column is greater than the existing value. Useful for time/version-based
        updates.
    :param returning_columns: List of columns to return after the operation. If
        specified, returns all rows that would have been inserted, including those with
        conflicts.
    :return: List of dictionaries with returned values if returning_columns is
        specified, otherwise None.
    """

    if on_conflict_update:
        if not conflict_columns:
            raise ValueError(
                "`conflict_columns` must be specified if `on_conflict_update` is True."
            )
        query_type = QueryType.UPSERT
    else:
        query_type = (
            QueryType.INSERT_IGNORE
            if conflict_columns is not None
            else QueryType.INSERT
        )

    conflict_columns = conflict_columns or []
    returned_values = []

    if update_columns is None:
        update_columns = [
            col.name
            for col in model.__table__.columns
            if col.name not in conflict_columns
        ]

    insert_stmt = insert(model).values(values)
    if query_type == QueryType.UPSERT:
        update_dict = {col: insert_stmt.excluded[col] for col in update_columns}

        # Automatically update update_ts column if it exists in the model.
        if hasattr(model, "update_ts") and "update_ts" not in update_dict:
            update_dict["update_ts"] = datetime.now(tz=timezone.utc)

        where_clause = (
            (
                insert_stmt.excluded[latest_check_column]
                > getattr(model, latest_check_column)
            )
            if latest_check_column
            else None
        )

        upsert_stmt = insert_stmt.on_conflict_do_update(
            index_elements=conflict_columns, set_=update_dict, where=where_clause
        )

        if returning_columns:
            upsert_stmt = upsert_stmt.returning(
                *[getattr(model, col) for col in returning_columns]
            )

    elif query_type == QueryType.INSERT:
        upsert_stmt = insert_stmt

        if returning_columns:
            upsert_stmt = upsert_stmt.returning(
                *[getattr(model, col) for col in returning_columns]
            )

    elif query_type == QueryType.INSERT_IGNORE:
        upsert_stmt = insert_stmt.on_conflict_do_nothing(
            index_elements=conflict_columns
        )

    else:
        raise ValueError(f"Invalid query type: {query_type}.")

    # Execute the upsert statement.
    # Only flushes, does NOT commit. Sends SQL immediately to database within current
    # transaction. Changes are visible within the same transaction but not committed.
    # Requires explicit session.commit() to persist permanently.
    result = session.execute(upsert_stmt)

    # Flush session to force immediate resolution of foreign key relationships
    # and catch any metadata/schema inconsistencies early.
    session.flush()

    if returning_columns:
        if query_type in [QueryType.UPSERT, QueryType.INSERT]:
            returned_values.extend([row._asdict() for row in result.fetchall()])

        elif query_type == QueryType.INSERT_IGNORE:
            # Since insert with conflict handling does not return values for ignored
            # rows, we must query the database to retrieve the values of those rows.
            # This query filters on the conflict columns to obtain all rows that would
            # have been inserted if no conflicts had occurred.
            conflict_conditions = [
                and_(
                    *[
                        (
                            getattr(model, col) == value[col]
                            if value[col] is not None
                            else getattr(model, col).is_(None)
                        )
                        for col in conflict_columns
                    ]
                )
                for value in values
            ]
            query = (
                session.query(model)
                .with_entities(*[getattr(model, col) for col in returning_columns])
                .filter(or_(*conflict_conditions))
            )
            returned_values.extend([row._asdict() for row in query.all()])

        else:
            raise ValueError(f"Invalid query type: {query_type}")

    return returned_values if returning_columns else None
