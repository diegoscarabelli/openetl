"""
Tests for the copy_records COPY helper in dags.lib.sql_utils.
"""

from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from dags.lib.sql_utils import copy_records


def test_copy_records_loads_rows(db_session: Session) -> None:
    """
    copy_records streams tuples into a table, writing NULL for None and preserving empty
    strings.

    :param db_session: SQLAlchemy session fixture bound to the test database.
    """
    db_session.execute(
        text("CREATE TEMP TABLE copy_records_test (a TEXT, b INTEGER, c NUMERIC)")
    )

    written = copy_records(
        db_session,
        "copy_records_test",
        ["a", "b", "c"],
        iter([("x", 1, "1.5"), ("y", 2, None), ("", 3, None)]),
    )
    assert written == 3

    rows = db_session.execute(
        text("SELECT a, b, c FROM copy_records_test ORDER BY b")
    ).all()
    assert rows[0] == ("x", 1, Decimal("1.5"))
    assert rows[1][0] == "y"
    assert rows[1][2] is None
    # An empty string round-trips as an empty string, not NULL.
    assert rows[2][0] == ""
    assert rows[2][2] is None
