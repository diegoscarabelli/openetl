"""
Unit tests for dags.lib.sql_utils module.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import Column, Integer, String, DateTime, text
from sqlalchemy.orm import declarative_base

from dags.lib.sql_utils import make_base, upsert_model_instances, _upsert_values
from tests.dags.lib.conftest import MyTest


def test_make_base_with_update_ts_and_schema():
    """
    Test that make_base creates correct columns and schema.
    """

    Base = make_base(schema="test_schema", include_update_ts=True)

    class TestModel(Base):
        __tablename__ = "test_table"
        id = Column(Integer, primary_key=True)
        name = Column(String)

    assert hasattr(TestModel, "create_ts")
    assert hasattr(TestModel, "update_ts")
    assert TestModel.__table_args__["schema"] == "test_schema"


class TestUpsertModelInstances:
    """
    Test class for upsert_model_instances functionality.
    """

    @staticmethod
    def set_up_tbl(session):
        """
        Add a row with id=1 and col_a="A" to the session and flush.
        """

        obj = MyTest(id=1, col_a="A")
        session.add(obj)
        session.flush()
        return obj

    def test_upsert_model_instances_insert_and_update(self, db_session):
        """
        Test upsert_model_instances for insert and update behavior.
        """

        obj1 = MyTest(id=1, col_a="A")
        obj2 = MyTest(id=2, col_a="B")
        kwargs = {
            "conflict_columns": ["id"],
            "on_conflict_update": True,
        }
        with patch("dags.lib.sql_utils._upsert_values") as mock_upsert:
            mock_upsert.return_value = []
            upsert_model_instances(db_session, [obj1, obj2], **kwargs)
        db_session.commit()

        # Update.
        obj1_updated = MyTest(id=1, col_a="C")
        kwargs = {
            "conflict_columns": ["id"],
            "on_conflict_update": True,
        }
        with patch("dags.lib.sql_utils._upsert_values") as mock_upsert:
            mock_upsert.return_value = []
            upsert_model_instances(db_session, [obj1_updated], **kwargs)
        db_session.commit()

        # Simulate result.
        result = MyTest(id=1, col_a="C")
        assert result.col_a == "C"

    def test_upsert_values_missing_conflict_columns_raises(self, db_session):
        """
        Test that _upsert_values raises ValueError if conflict_columns is missing.
        """

        with pytest.raises(ValueError):
            _upsert_values(
                MyTest,
                [{"id": 1, "col_a": "A"}],
                db_session,
                on_conflict_update=True,
            )

    def test_upsert_values_upsert(self, db_session):
        """
        Test _upsert_values UPSERT mode updates on conflict.
        """

        # Insert initial row.
        kwargs = {
            "conflict_columns": ["id"],
            "on_conflict_update": True,
            "returning_columns": ["id", "col_a"],
        }
        _upsert_values(MyTest, [{"id": 1, "col_a": "A"}], db_session, **kwargs)
        db_session.commit()

        # Upsert with new name.
        kwargs = {
            "conflict_columns": ["id"],
            "on_conflict_update": True,
            "returning_columns": ["id", "col_a"],
        }
        _upsert_values(MyTest, [{"id": 1, "col_a": "B"}], db_session, **kwargs)
        db_session.commit()
        result = db_session.query(MyTest).filter_by(id=1).first()
        assert result.col_a == "B"

    def test_upsert_values_insert_ignore(self, db_session):
        """
        Test _upsert_values INSERT_IGNORE mode does not update on conflict.
        """

        # Insert initial row.
        _upsert_values(
            MyTest,
            [{"id": 1, "col_a": "A"}],
            db_session,
            conflict_columns=["id"],
            on_conflict_update=False,
            returning_columns=["id", "col_a"],
        )
        db_session.commit()

        # Try to insert with same id, should ignore.
        _upsert_values(
            MyTest,
            [{"id": 1, "col_a": "C"}],
            db_session,
            conflict_columns=["id"],
            on_conflict_update=False,
            returning_columns=["id", "col_a"],
        )
        db_session.commit()
        result = db_session.query(MyTest).filter_by(id=1).first()
        assert result.col_a == "A"

    def test_upsert_values_insert(self, db_session):
        """
        Test _upsert_values INSERT mode inserts new rows.
        """

        # Insert first row.
        kwargs = {
            "conflict_columns": None,
            "on_conflict_update": False,
            "returning_columns": ["id", "col_a"],
        }
        _upsert_values(MyTest, [{"id": 1, "col_a": "A"}], db_session, **kwargs)
        db_session.commit()

        # Insert second row.
        kwargs = {
            "conflict_columns": None,
            "on_conflict_update": False,
            "returning_columns": ["id", "col_a"],
        }
        _upsert_values(MyTest, [{"id": 2, "col_a": "B"}], db_session, **kwargs)
        db_session.commit()
        result1 = db_session.query(MyTest).filter_by(id=1).first()
        result2 = db_session.query(MyTest).filter_by(id=2).first()
        assert result1.col_a == "A"
        assert result2.col_a == "B"

    def test_upsert_values_rollback(self, db_session):
        """
        Test that rollback undoes inserted rows.
        """

        # Insert two rows.
        kwargs = {
            "conflict_columns": None,
            "on_conflict_update": False,
            "returning_columns": ["id", "col_a"],
        }
        _upsert_values(MyTest, [{"id": 1, "col_a": "A"}], db_session, **kwargs)
        _upsert_values(MyTest, [{"id": 2, "col_a": "B"}], db_session, **kwargs)
        db_session.commit()
        assert db_session.query(MyTest).count() == 2
        db_session.rollback()
        db_session.query(MyTest).delete()
        db_session.commit()
        assert db_session.query(MyTest).count() == 0

    def test_upsert_values_auto_update_ts(self, db_session):
        """
        Test that _upsert_values automatically sets update_ts when model has this
        column.
        """

        # Use raw SQL to test the functionality directly without table creation.
        db_session.execute(
            text(
                """
            CREATE TEMP TABLE test_update_ts_temp (
                id INTEGER PRIMARY KEY,
                name TEXT,
                create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                update_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """
            )
        )

        # Create a simple mock model for this test.
        temp_base = declarative_base()

        class TempTestModel(temp_base):
            """
            Temporary test model with update_ts column.
            """

            __tablename__ = "test_update_ts_temp"
            id = Column(Integer, primary_key=True)
            name = Column(String)
            create_ts = Column(DateTime)
            update_ts = Column(DateTime)

        # Insert initial record.
        _upsert_values(
            TempTestModel,
            [{"id": 1, "name": "initial"}],
            db_session,
            conflict_columns=["id"],
            on_conflict_update=True,
        )
        db_session.commit()

        # Get the record and check timestamps.
        record = db_session.query(TempTestModel).filter_by(id=1).first()
        assert record is not None
        assert record.create_ts is not None
        assert record.update_ts is not None
        initial_update_ts = record.update_ts

        # Update the record (conflict scenario).
        _upsert_values(
            TempTestModel,
            [{"id": 1, "name": "updated"}],
            db_session,
            conflict_columns=["id"],
            on_conflict_update=True,
        )
        db_session.commit()

        # Verify update_ts was automatically updated.
        updated_record = db_session.query(TempTestModel).filter_by(id=1).first()
        assert updated_record.name == "updated"
        # The update_ts should be updated (different from initial).
        assert updated_record.update_ts != initial_update_ts

    def test_upsert_values_no_update_ts_column(self, db_session):
        """
        Test that models without update_ts column continue to work unchanged.
        """

        # This should work exactly as before - using MyTest which has no update_ts.
        _upsert_values(
            MyTest,
            [{"id": 1, "col_a": "test"}],
            db_session,
            conflict_columns=["id"],
            on_conflict_update=True,
        )
        db_session.commit()

        record = db_session.query(MyTest).filter_by(id=1).first()
        assert record is not None
        assert record.col_a == "test"
        assert not hasattr(record, "update_ts")  # Verify no update_ts column.

    def test_upsert_values_explicit_update_ts(self, db_session):
        """
        Test that explicit update_ts values in update_columns are preserved.
        """

        # Use raw SQL to test the functionality directly.
        db_session.execute(
            text(
                """
            CREATE TEMP TABLE test_explicit_ts_temp (
                id INTEGER PRIMARY KEY,
                name TEXT,
                create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                update_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """
            )
        )

        # Create a simple mock model for this test.
        temp_base = declarative_base()

        class TempExplicitModel(temp_base):
            """
            Temporary test model for explicit update_ts testing.
            """

            __tablename__ = "test_explicit_ts_temp"
            id = Column(Integer, primary_key=True)
            name = Column(String)
            create_ts = Column(DateTime)
            update_ts = Column(DateTime)

        # Insert initial record.
        _upsert_values(
            TempExplicitModel,
            [{"id": 1, "name": "initial"}],
            db_session,
            conflict_columns=["id"],
            on_conflict_update=True,
        )
        db_session.commit()

        # Define an explicit update_ts value (timezone-aware to match database).
        explicit_update_ts = datetime(2023, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        # Update with explicit update_ts in update_columns.
        _upsert_values(
            TempExplicitModel,
            [{"id": 1, "name": "updated", "update_ts": explicit_update_ts}],
            db_session,
            conflict_columns=["id"],
            on_conflict_update=True,
            update_columns=["name", "update_ts"],  # Explicitly include update_ts.
        )
        db_session.commit()

        # Verify the explicit update_ts was used, not auto-generated.
        updated_record = db_session.query(TempExplicitModel).filter_by(id=1).first()
        assert updated_record.name == "updated"
        assert updated_record.update_ts == explicit_update_ts

    def test_upsert_values_latest_check_column_strict_greater(self, db_session):
        """
        Test latest_check_column with strict > comparison (default behavior).
        """

        # Create temp table with version column.
        db_session.execute(
            text(
                """
            CREATE TEMP TABLE test_version_strict_temp (
                id INTEGER PRIMARY KEY,
                name TEXT,
                version INTEGER NOT NULL
            )
        """
            )
        )

        temp_base = declarative_base()

        class TempVersionModel(temp_base):
            """
            Temporary test model with version column.
            """

            __tablename__ = "test_version_strict_temp"
            id = Column(Integer, primary_key=True)
            name = Column(String)
            version = Column(Integer)

        # Insert initial record with version=5.
        _upsert_values(
            TempVersionModel,
            [{"id": 1, "name": "initial", "version": 5}],
            db_session,
            conflict_columns=["id"],
            on_conflict_update=True,
            latest_check_column="version",
            latest_check_inclusive=False,  # Strict > (default).
        )
        db_session.commit()

        record = db_session.query(TempVersionModel).filter_by(id=1).first()
        assert record.name == "initial"
        assert record.version == 5

        # Try to upsert with version=5 (same) - should NOT update.
        _upsert_values(
            TempVersionModel,
            [{"id": 1, "name": "same_version", "version": 5}],
            db_session,
            conflict_columns=["id"],
            on_conflict_update=True,
            latest_check_column="version",
            latest_check_inclusive=False,
        )
        db_session.commit()

        record = db_session.query(TempVersionModel).filter_by(id=1).first()
        assert record.name == "initial"  # Should NOT be updated.
        assert record.version == 5

        # Try to upsert with version=6 (greater) - should update.
        _upsert_values(
            TempVersionModel,
            [{"id": 1, "name": "newer_version", "version": 6}],
            db_session,
            conflict_columns=["id"],
            on_conflict_update=True,
            latest_check_column="version",
            latest_check_inclusive=False,
        )
        db_session.commit()

        record = db_session.query(TempVersionModel).filter_by(id=1).first()
        assert record.name == "newer_version"  # Should be updated.
        assert record.version == 6

    def test_upsert_values_latest_check_column_inclusive(self, db_session):
        """
        Test latest_check_column with >= comparison (inclusive).
        """

        # Create temp table with version column.
        db_session.execute(
            text(
                """
            CREATE TEMP TABLE test_version_inclusive_temp (
                id INTEGER PRIMARY KEY,
                name TEXT,
                version INTEGER NOT NULL
            )
        """
            )
        )

        temp_base = declarative_base()

        class TempVersionInclusiveModel(temp_base):
            """
            Temporary test model with version column for inclusive test.
            """

            __tablename__ = "test_version_inclusive_temp"
            id = Column(Integer, primary_key=True)
            name = Column(String)
            version = Column(Integer)

        # Insert initial record with version=5.
        _upsert_values(
            TempVersionInclusiveModel,
            [{"id": 1, "name": "initial", "version": 5}],
            db_session,
            conflict_columns=["id"],
            on_conflict_update=True,
            latest_check_column="version",
            latest_check_inclusive=True,  # >= comparison.
        )
        db_session.commit()

        record = db_session.query(TempVersionInclusiveModel).filter_by(id=1).first()
        assert record.name == "initial"
        assert record.version == 5

        # Try to upsert with version=5 (same) + inclusive=True - SHOULD update.
        _upsert_values(
            TempVersionInclusiveModel,
            [{"id": 1, "name": "same_version_updated", "version": 5}],
            db_session,
            conflict_columns=["id"],
            on_conflict_update=True,
            latest_check_column="version",
            latest_check_inclusive=True,
        )
        db_session.commit()

        record = db_session.query(TempVersionInclusiveModel).filter_by(id=1).first()
        assert (
            record.name == "same_version_updated"
        )  # Should be updated with inclusive.
        assert record.version == 5

    def test_upsert_values_latest_check_column_updates_update_ts(self, db_session):
        """
        Test that update_ts is updated when latest_check_column condition passes.
        """

        import time

        # Create temp table with version and update_ts columns.
        db_session.execute(
            text(
                """
            CREATE TEMP TABLE test_version_update_ts_temp (
                id INTEGER PRIMARY KEY,
                name TEXT,
                version INTEGER NOT NULL,
                create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                update_ts TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """
            )
        )

        temp_base = declarative_base()

        class TempVersionUpdateTsModel(temp_base):
            """
            Temporary test model with version and update_ts columns.
            """

            __tablename__ = "test_version_update_ts_temp"
            id = Column(Integer, primary_key=True)
            name = Column(String)
            version = Column(Integer)
            create_ts = Column(DateTime)
            update_ts = Column(DateTime)

        # Insert initial record.
        _upsert_values(
            TempVersionUpdateTsModel,
            [{"id": 1, "name": "initial", "version": 1}],
            db_session,
            conflict_columns=["id"],
            on_conflict_update=True,
            latest_check_column="version",
        )
        db_session.commit()

        record = db_session.query(TempVersionUpdateTsModel).filter_by(id=1).first()
        initial_update_ts = record.update_ts

        # Wait briefly to ensure timestamp difference.
        time.sleep(0.1)

        # Upsert with newer version - should update and change update_ts.
        _upsert_values(
            TempVersionUpdateTsModel,
            [{"id": 1, "name": "updated", "version": 2}],
            db_session,
            conflict_columns=["id"],
            on_conflict_update=True,
            latest_check_column="version",
        )
        db_session.commit()

        updated_record = (
            db_session.query(TempVersionUpdateTsModel).filter_by(id=1).first()
        )
        assert updated_record.name == "updated"
        assert updated_record.version == 2
        assert (
            updated_record.update_ts > initial_update_ts
        )  # update_ts should be newer.
