import os
import json

from typing import Generator

import pytest
from dotenv import load_dotenv

from sqlalchemy import Boolean, create_engine, Column, Integer, String, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session

from dags.lib.etl_monitor_utils import InfraMonitorBase, ETLResultSqla


# Load environment variables from .env file.
load_dotenv()


def get_postgres_password() -> str:
    """
    Load the Postgres password from the credentials JSON file.

    :return: The password value, or 'postgres' if not found.
    """

    sql_credentials_dir = os.getenv("SQL_CREDENTIALS_DIR")
    if not sql_credentials_dir:
        raise RuntimeError(
            "SQL_CREDENTIALS_DIR environment variable is not set. "
            "Please set it in your .env file."
        )

    # Expand user home directory (~) in the path.
    sql_credentials_dir = os.path.expanduser(sql_credentials_dir)
    cred_path = os.path.join(sql_credentials_dir, "postgres.json")
    with open(cred_path, "r", encoding="utf-8") as f:
        creds = json.load(f)
    return creds.get("password", "postgres")


POSTGRES_PASSWORD = get_postgres_password()

# Test database URL configuration.
# Default behavior assumes the test database is a PostgreSQL database running
# locally (accessible via localhost), which is the standard setup for software
# development and testing environments. The default connects to the `postgres`
# database on `localhost:5432` using the `postgres` user credentials.
# This assumption can be overridden by setting the `TEST_DB_URL` environment
# variable to point to a database on a different host (e.g., a remote test
# database server). The `TEST_DB_URL` should be a complete SQLAlchemy connection
# string (e.g., postgresql+psycopg2://user:password@host:port/database).
TEST_DB_URL = os.getenv("TEST_DB_URL") or (
    f"postgresql+psycopg2://postgres:{POSTGRES_PASSWORD}@localhost:5432/postgres"
)

Base = declarative_base()


class MyTest(Base):
    """
    SQLAlchemy ORM model for the test table 'sql_utils_test_tbl'.
    """

    __tablename__ = "sql_utils_test_tbl"
    __table_args__ = {"schema": "public"}

    id = Column(Integer, primary_key=True)
    col_a = Column(String, nullable=False)
    col_b = Column(String)
    col_c = Column(Integer)
    latest = Column(Boolean, server_default=text("false"))

    def __eq__(self, other) -> bool:
        """
        Compare two MyTest instances for equality.
        """

        return (
            self.id == other.id
            and self.col_a == other.col_a
            and self.col_b == other.col_b
            and self.col_c == other.col_c
            and self.latest == other.latest
        )

    def __lt__(self, other) -> bool:
        """
        Compare two MyTest instances for sorting by id.
        """

        return self.id < other.id

    def __repr__(self) -> str:
        """
        String representation of MyTest instance.
        """

        return (
            f"<MyTest(id={self.id}, col_a={self.col_a}, col_b={self.col_b}, "
            f"col_c={self.col_c}, latest={self.latest})>"
        )


@pytest.fixture(scope="function")
def db_engine() -> Generator[Engine, None, None]:
    """
    Pytest fixture for creating and tearing down the test database engine.

    :return: The SQLAlchemy engine instance.
    """

    engine = create_engine(TEST_DB_URL)
    MyTest.metadata.create_all(engine)
    yield engine
    MyTest.metadata.drop_all(engine)


@pytest.fixture(scope="function")
def db_session(db_engine: Engine) -> Generator[Session, None, None]:
    """
    Pytest fixture for creating and closing a database session.

    :param db_engine: The SQLAlchemy engine instance.
    :return: The SQLAlchemy session instance.
    """

    session = sessionmaker(bind=db_engine)()
    yield session
    session.close()


@pytest.fixture(scope="function")
def etl_result_engine() -> Generator[Engine, None, None]:
    """
    Pytest fixture for creating and tearing down the reporting engine and schema.

    :return: The SQLAlchemy engine instance for reporting.
    """

    engine = create_engine(TEST_DB_URL)
    with engine.begin() as conn:
        # Drop schema if exists.
        conn.execute(text("DROP SCHEMA IF EXISTS infra_monitor CASCADE"))
        # Create schema.
        conn.execute(text("CREATE SCHEMA IF NOT EXISTS infra_monitor"))

    InfraMonitorBase.metadata.create_all(engine, tables=[ETLResultSqla.__table__])
    yield engine
    InfraMonitorBase.metadata.drop_all(engine, tables=[ETLResultSqla.__table__])


@pytest.fixture(scope="function")
def etl_result_session(etl_result_engine: Engine) -> Generator[Session, None, None]:
    """
    Pytest fixture for creating and closing a reporting database session.

    :param reporting_engine: The SQLAlchemy engine instance for reporting.
    :return: The SQLAlchemy session instance for reporting.
    """

    session = sessionmaker(bind=etl_result_engine)()
    yield session
    session.close()
