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
from typing import Any, Dict, List, Optional, Type

from sqlalchemy import create_engine, DateTime, ForeignKey, MetaData
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    declared_attr,
    mapped_column,
)

from dags.lib.logging_utils import LOGGER

# psycopg3 (libpq) rejects queries with more than 65 535
# parameters. Upserts that exceed this limit are split into
# chunks automatically by _upsert_values().
_PSYCOPG_MAX_PARAMS = 65_535


# Enum for query types used in upsert logic.
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
) -> Type:
    """
    Create a custom base class for SQLAlchemy ORM models representing SQL database
    tables.

    :param schema: Schema name for the SQL database table.
    :param include_update_ts: Whether to include an update timestamp column.
    :param metadata: SQLAlchemy MetaData instance to share across models.
    :return: Declarative base class for ORM models.
    """
    _metadata = metadata or MetaData()

    class _Base(DeclarativeBase):
        metadata = _metadata  # type: ignore[assignment]

    class _CustomBase(_Base):
        """
        Custom SQLAlchemy ORM base class with optional schema and timestamp columns.
        """

        __abstract__ = True

        @declared_attr
        def create_ts(cls) -> Mapped[datetime]:
            """
            Auto-populated creation timestamp.
            """
            return mapped_column(
                DateTime(timezone=True),
                default=datetime.now,
                nullable=False,
            )

    if include_update_ts:

        class _CustomBaseWithTs(_CustomBase):
            __abstract__ = True

            @declared_attr
            def update_ts(cls) -> Mapped[datetime]:
                """
                Auto-populated update timestamp.
                """
                return mapped_column(
                    DateTime(timezone=True),
                    default=datetime.now,
                    onupdate=datetime.now,
                    nullable=False,
                )

        result_base = _CustomBaseWithTs
    else:
        result_base = _CustomBase

    if schema:
        result_base.__table_args__ = {"schema": schema}
    return result_base


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
    model_instances: List[Any],
    update_columns: Optional[List[str]] = None,
    conflict_columns: Optional[List[str]] = None,
    on_conflict_update: bool = False,
    latest_check_column: str = None,
    latest_check_inclusive: bool = False,
    returning_columns: Optional[List[str]] = None,
    chunk_size: int = 10_000,
) -> Optional[List[Any]]:
    """
    Bulk upsert SQLAlchemy ORM model instances into SQL database tables, handling
    conflicts and optionally updating existing rows. This function converts model
    instances to dictionaries, delegates the upsert logic to a lower-level helper, and
    optionally returns the persisted instances as they exist in the database after the
    operation.

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
        column is greater than (or greater than or equal to, if latest_check_inclusive
        is True) the existing value. Useful for time/version-based updates.
    :param latest_check_inclusive: If True, use >= comparison for latest_check_column
        instead of >. Defaults to False (strict greater than).
    :param returning_columns: List of column names to return via RETURNING.
        Must be a non-empty list of valid model column names. If None, no
        RETURNING is issued and the function returns None.

        Result-shape contract by mode:

        - INSERT (no conflict_columns), INSERT_IGNORE, plain UPSERT: result
          contains exactly one entry per input row in input order
          (position-aligned).
        - UPSERT + `latest_check_column`: NOT position-aligned. Conflicted rows
          whose incoming value fails the latest-check `WHERE` clause produce
          no `RETURNING` row (PostgreSQL treats the conflict as DO NOTHING in
          that case), so the result list is SHORTER than the input list.
          Callers in this regime must reconcile rows by their conflict-key
          values, not by index.

        Operational side effect (INSERT_IGNORE + returning_columns only): the
        helper rewrites internally as a no-op `ON CONFLICT DO UPDATE SET
        <conflict_col> = excluded.<conflict_col>` so `RETURNING` fires for
        conflicted rows. This still executes an UPDATE in PostgreSQL: it can
        fire UPDATE triggers, generate a new row version (WAL traffic), and
        take stronger locks than pure `DO NOTHING`. The pure `DO NOTHING`
        path is preserved when `returning_columns` is None, so callers that
        want to skip the row-write entirely on conflict still can by
        omitting `returning_columns`.
    :param chunk_size: Maximum rows per INSERT statement. Clamped internally so the
        total parameter count never exceeds the psycopg3 limit.
    :return: List of SQLAlchemy model instances (with only the requested columns
        populated) if returning_columns is specified, otherwise None.
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
        latest_check_inclusive=latest_check_inclusive,
        returning_columns=returning_columns,
        chunk_size=chunk_size,
    )

    if results is None:
        return None

    return [model(**result) for result in results]


def _upsert_values(
    model: Type,
    values: List[dict],
    session: Session,
    update_columns: Optional[List[str]] = None,
    conflict_columns: Optional[List[str]] = None,
    on_conflict_update: bool = False,
    latest_check_column: str = None,
    latest_check_inclusive: bool = False,
    returning_columns: Optional[List[str]] = None,
    chunk_size: int = 10_000,
) -> Optional[List[Dict[str, Any]]]:
    """
    Bulk upsert dictionaries of values into SQL database tables using SQLAlchemy ORM
    models and sessions, supporting conflict resolution and conditional updates. This
    function builds and executes the appropriate SQL statement for insert, upsert, or
    insert-ignore, and can return the resulting rows as dictionaries if requested. Large
    value lists are split into chunks to stay within the psycopg3 parameter limit.

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
        column is greater than (or greater than or equal to, if latest_check_inclusive
        is True) the existing value. Useful for time/version-based updates.
    :param latest_check_inclusive: If True, use >= comparison for latest_check_column
        instead of >. Defaults to False (strict greater than).
    :param returning_columns: List of columns to return after the operation.
        Must be a non-empty list of valid model column names.

        Result-shape contract by mode:

        - INSERT, INSERT_IGNORE, plain UPSERT: one row per input row in input
          order (position-aligned).
        - UPSERT + `latest_check_column`: NOT position-aligned. When the
          latest-check `WHERE` clause prevents the update, PostgreSQL treats
          the conflict as DO NOTHING and emits no `RETURNING` row, so the
          result list is shorter than the input list. Reconcile by
          conflict-key value, not by index.

        For INSERT_IGNORE the helper internally rewrites the statement using
        a no-op `DO UPDATE` (assigning a conflict column to itself) so
        `RETURNING` fires for both newly-inserted and conflicted rows; this
        means an UPDATE actually executes in PostgreSQL on conflict (UPDATE
        triggers can fire, a new row version is written to WAL, stronger
        locks are taken than under pure DO NOTHING). The pure DO NOTHING
        path is preserved when `returning_columns` is None.
    :param chunk_size: Maximum rows per INSERT statement. Clamped internally so the
        total parameter count never exceeds the psycopg3 limit.
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
        query_type = QueryType.INSERT_IGNORE if conflict_columns else QueryType.INSERT

    conflict_columns = conflict_columns or []
    model_columns = model.__table__.columns.keys()

    # Validate `returning_columns` so callers get a clear ValueError up front
    # instead of either an opaque AttributeError from `getattr(model, col)`
    # further down (unknown column case) or a silent empty-list result that
    # superficially looks like "no rows came back" (empty-list case). This
    # validation is unrelated to the documented `latest_check_column`
    # shorter-than-input result; that case is intentional and handled in the
    # main result-shape contract in the docstring.
    if returning_columns is not None:
        if not returning_columns:
            raise ValueError(
                "`returning_columns` must be a non-empty list when provided. "
                "Pass None to opt out of the RETURNING path."
            )
        unknown = [col for col in returning_columns if col not in model_columns]
        if unknown:
            raise ValueError(
                f"`returning_columns` references column(s) not present on "
                f"{model.__name__}: {unknown}. Valid columns: "
                f"{sorted(model_columns)}"
            )

    returned_values: List[Dict[str, Any]] = []

    # Default update_columns excludes:
    # - conflict columns (used to identify the row, must not change),
    # - primary-key columns (immutable; for an auto-increment PK that's not
    #   present on the input dict, leaving it would generate `SET pk = NULL`
    #   and either fail or assign a new sequence value),
    # - create_ts (audit column; `make_base` defaults populate it on insert),
    # - update_ts (set explicitly inside the UPSERT branch below if present).
    pk_columns = {col.name for col in model.__table__.primary_key.columns}
    if update_columns is None:
        excluded_cols = set(conflict_columns) | pk_columns | {"create_ts", "update_ts"}
        update_columns = [col for col in model_columns if col not in excluded_cols]

    # Clamp chunk_size so total parameters stay within the psycopg3 limit.
    # Use the full model column count because SQLAlchemy fills in columns
    # with Python-side defaults even when omitted from the values dicts.
    num_cols = len(model.__table__.columns)
    max_rows = max(1, min(chunk_size, _PSYCOPG_MAX_PARAMS // num_cols))

    for chunk_start in range(0, len(values), max_rows):
        chunk = values[chunk_start : chunk_start + max_rows]

        insert_stmt = insert(model).values(chunk)

        if query_type == QueryType.UPSERT:
            update_dict = {col: insert_stmt.excluded[col] for col in update_columns}

            # Automatically update update_ts column if it exists in the model.
            if hasattr(model, "update_ts") and "update_ts" not in update_dict:
                update_dict["update_ts"] = datetime.now(tz=timezone.utc)

            if latest_check_column:
                excluded_col = insert_stmt.excluded[latest_check_column]
                existing_col = getattr(model, latest_check_column)
                where_clause = (
                    excluded_col >= existing_col
                    if latest_check_inclusive
                    else excluded_col > existing_col
                )
            else:
                where_clause = None

            upsert_stmt = insert_stmt.on_conflict_do_update(
                index_elements=conflict_columns,
                set_=update_dict,
                where=where_clause,
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
            if returning_columns:
                # "No-op DO UPDATE" trick: ON CONFLICT DO NOTHING does not emit
                # RETURNING rows for ignored conflicts, so a follow-up SELECT
                # over the conflict keys is required to recover IDs. That
                # SELECT returns rows in undefined order and de-duplicates by
                # conflict key, breaking position-alignment between input and
                # result.
                #
                # Trick: rewrite as `DO UPDATE SET <conflict_col> = excluded.
                # <conflict_col>`. The conflict column's existing value is by
                # definition equal to the incoming value (that's what triggered
                # the conflict), so assigning it to itself is a provable no-op
                # at the value level. The conflict path still *fires*, which
                # makes RETURNING emit one row per input row in input order,
                # for both fresh inserts and conflicts.
                #
                # We deliberately do NOT include `update_ts` in the SET clause
                # here, so the do-nothing contract is preserved at the audit-
                # column level too (a conflicted row's update_ts stays at its
                # original value).
                #
                # The pure DO NOTHING path is still used when
                # returning_columns is None, so callers that want to skip the
                # row-write entirely on conflict are unaffected.
                key_col = conflict_columns[0]
                upsert_stmt = insert_stmt.on_conflict_do_update(
                    index_elements=conflict_columns,
                    set_={key_col: insert_stmt.excluded[key_col]},
                ).returning(*[getattr(model, col) for col in returning_columns])
            else:
                upsert_stmt = insert_stmt.on_conflict_do_nothing(
                    index_elements=conflict_columns,
                )

        else:
            raise ValueError(f"Invalid query type: {query_type}.")

        # Execute (no commit). Sends SQL to the database within the current
        # transaction. Requires explicit session.commit() by the caller.
        result = session.execute(upsert_stmt)

        if returning_columns:
            # All three branches above attach RETURNING when returning_columns
            # is set (UPSERT and INSERT directly; INSERT_IGNORE via the no-op
            # DO UPDATE trick). The result is one row per input row in input
            # order for the INSERT, INSERT_IGNORE, and plain-UPSERT paths.
            #
            # Caveat: UPSERT + `latest_check_column` may emit fewer rows than
            # the input chunk — when the WHERE clause on the DO UPDATE blocks
            # an update, PostgreSQL treats the conflict as DO NOTHING and
            # emits no RETURNING row for that input. Callers in this regime
            # must reconcile by conflict-key value, not by index.
            returned_values.extend([row._asdict() for row in result.fetchall()])

    return returned_values if returning_columns else None
