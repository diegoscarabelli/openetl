"""
Unit tests for dags.lib.sql_utils module.
"""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import Column, Integer, String, DateTime, delete, func, select, text
from sqlalchemy.orm import DeclarativeBase

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
            mock_upsert.return_value = None
            result = upsert_model_instances(db_session, [obj1, obj2], **kwargs)

        # Default returning_columns=None passes None to _upsert_values.
        assert mock_upsert.call_args.kwargs["returning_columns"] is None
        assert result is None
        db_session.commit()

        # Update with explicit returning_columns.
        obj1_updated = MyTest(id=1, col_a="C")
        kwargs = {
            "conflict_columns": ["id"],
            "on_conflict_update": True,
            "returning_columns": ["id", "col_a"],
        }
        with patch("dags.lib.sql_utils._upsert_values") as mock_upsert:
            mock_upsert.return_value = [{"id": 1, "col_a": "C"}]
            result = upsert_model_instances(db_session, [obj1_updated], **kwargs)

        # returning_columns is passed through to _upsert_values.
        assert mock_upsert.call_args.kwargs["returning_columns"] == [
            "id",
            "col_a",
        ]
        assert len(result) == 1
        assert result[0].col_a == "C"

    def test_upsert_model_instances_returning_columns_integration(self, db_session):
        """
        Test upsert_model_instances with returning_columns against real DB.
        """
        obj = MyTest(id=1, col_a="A", col_b="B")
        result = upsert_model_instances(
            db_session,
            [obj],
            conflict_columns=["id"],
            on_conflict_update=True,
            returning_columns=["id", "col_a"],
        )
        db_session.commit()
        assert len(result) == 1
        assert result[0].id == 1
        assert result[0].col_a == "A"

    def test_upsert_model_instances_no_returning_columns(self, db_session):
        """
        Test upsert_model_instances without returning_columns returns None.
        """
        obj = MyTest(id=1, col_a="A")
        result = upsert_model_instances(
            db_session,
            [obj],
            conflict_columns=["id"],
            on_conflict_update=True,
        )
        db_session.commit()
        assert result is None
        # Row should still exist.
        row = db_session.execute(select(MyTest).where(MyTest.id == 1)).scalars().first()
        assert row.col_a == "A"

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
        result = (
            db_session.execute(select(MyTest).where(MyTest.id == 1)).scalars().first()
        )
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
        result = (
            db_session.execute(select(MyTest).where(MyTest.id == 1)).scalars().first()
        )
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
        result1 = (
            db_session.execute(select(MyTest).where(MyTest.id == 1)).scalars().first()
        )
        result2 = (
            db_session.execute(select(MyTest).where(MyTest.id == 2)).scalars().first()
        )
        assert result1.col_a == "A"
        assert result2.col_a == "B"

    def test_upsert_values_insert_ignore_returning_position_aligned(self, db_session):
        """
        INSERT_IGNORE with `returning_columns` returns one row per input row, in input
        order (position-aligned), with existing values preserved for conflicted rows.

        Implemented via the no-op DO UPDATE trick.
        """
        # Pre-seed two rows that will conflict on the second pass.
        _upsert_values(
            MyTest,
            [{"id": 1, "col_a": "A"}, {"id": 3, "col_a": "C"}],
            db_session,
            conflict_columns=["id"],
            on_conflict_update=False,
            returning_columns=["id", "col_a"],
        )
        db_session.commit()

        # Mix of conflict (id=1), new (id=2), conflict (id=3) in non-trivial
        # order to stress position-alignment.
        rows = _upsert_values(
            MyTest,
            [
                {"id": 1, "col_a": "Z"},  # conflict, existing A wins
                {"id": 2, "col_a": "B"},  # new
                {"id": 3, "col_a": "Z"},  # conflict, existing C wins
            ],
            db_session,
            conflict_columns=["id"],
            on_conflict_update=False,
            returning_columns=["id", "col_a"],
        )
        db_session.commit()
        assert [r["id"] for r in rows] == [1, 2, 3]
        assert [r["col_a"] for r in rows] == ["A", "B", "C"]
        db_session.execute(delete(MyTest))
        db_session.commit()

    def test_upsert_values_returning_columns_validation(self, db_session):
        """
        `returning_columns=[]` and unknown column names raise clear ValueErrors instead
        of opaque downstream failures (silent empty list / bare AttributeError from
        getattr).
        """
        with pytest.raises(ValueError, match="non-empty"):
            _upsert_values(
                MyTest,
                [{"id": 1, "col_a": "A"}],
                db_session,
                conflict_columns=["id"],
                on_conflict_update=True,
                returning_columns=[],
            )
        with pytest.raises(ValueError, match="not_a_column"):
            _upsert_values(
                MyTest,
                [{"id": 1, "col_a": "A"}],
                db_session,
                conflict_columns=["id"],
                on_conflict_update=True,
                returning_columns=["id", "not_a_column"],
            )

    def test_upsert_values_default_update_columns_exclude_pk(self, db_session):
        """
        Default `update_columns` excludes primary-key columns even when the PK is
        not in `conflict_columns`. Prevents `SET pk = NULL` corruption when an
        auto-increment PK is upserted with a separate uniqueness key.
        """
        from sqlalchemy import Column, Integer, String, UniqueConstraint
        from sqlalchemy.orm import DeclarativeBase

        class Base(DeclarativeBase):
            pass

        class AutoPK(Base):
            __tablename__ = "sql_utils_test_autopk"
            __table_args__ = (UniqueConstraint("user_id", "ts", name="autopk_unique"),)
            pk = Column(Integer, primary_key=True, autoincrement=True)
            user_id = Column(Integer, nullable=False)
            ts = Column(Integer, nullable=False)
            payload = Column(String, nullable=False)

        engine = db_session.get_bind()
        Base.metadata.create_all(engine)
        try:
            first = _upsert_values(
                AutoPK,
                [{"user_id": 1, "ts": 100, "payload": "v1"}],
                db_session,
                conflict_columns=["user_id", "ts"],
                on_conflict_update=True,
                returning_columns=["pk", "payload"],
            )
            db_session.commit()
            second = _upsert_values(
                AutoPK,
                [{"user_id": 1, "ts": 100, "payload": "v2"}],
                db_session,
                conflict_columns=["user_id", "ts"],
                on_conflict_update=True,
                returning_columns=["pk", "payload"],
            )
            db_session.commit()
            # PK is preserved across the conflict update; payload is updated.
            assert first[0]["pk"] == second[0]["pk"]
            assert second[0]["payload"] == "v2"
        finally:
            Base.metadata.drop_all(engine)

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
        count = db_session.execute(select(func.count()).select_from(MyTest)).scalar()
        assert count == 2
        db_session.rollback()
        db_session.execute(delete(MyTest))
        db_session.commit()
        count = db_session.execute(select(func.count()).select_from(MyTest)).scalar()
        assert count == 0

    def test_upsert_values_auto_update_ts(self, db_session):
        """
        Test that _upsert_values automatically sets update_ts when model has this
        column.
        """
        # Use raw SQL to test the functionality directly without table creation.
        db_session.execute(
            text(
                "CREATE TEMP TABLE test_update_ts_temp ("
                " id INTEGER PRIMARY KEY,"
                " name TEXT,"
                " create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),"
                " update_ts TIMESTAMPTZ NOT NULL DEFAULT NOW())"
            )
        )

        # Create a simple mock model for this test.
        class TempBase(DeclarativeBase):
            pass

        class TempTestModel(TempBase):
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
        record = (
            db_session.execute(select(TempTestModel).where(TempTestModel.id == 1))
            .scalars()
            .first()
        )
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
        updated_record = (
            db_session.execute(select(TempTestModel).where(TempTestModel.id == 1))
            .scalars()
            .first()
        )
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

        record = (
            db_session.execute(select(MyTest).where(MyTest.id == 1)).scalars().first()
        )
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
                "CREATE TEMP TABLE test_explicit_ts_temp ("
                " id INTEGER PRIMARY KEY,"
                " name TEXT,"
                " create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),"
                " update_ts TIMESTAMPTZ NOT NULL DEFAULT NOW())"
            )
        )

        # Create a simple mock model for this test.
        class TempBase(DeclarativeBase):
            pass

        class TempExplicitModel(TempBase):
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
        updated_record = (
            db_session.execute(
                select(TempExplicitModel).where(TempExplicitModel.id == 1)
            )
            .scalars()
            .first()
        )
        assert updated_record.name == "updated"
        assert updated_record.update_ts == explicit_update_ts

    def test_upsert_values_latest_check_column_strict_greater(self, db_session):
        """
        Test latest_check_column with strict > comparison (default behavior).
        """
        # Create temp table with version column.
        db_session.execute(
            text(
                "CREATE TEMP TABLE test_version_strict_temp ("
                " id INTEGER PRIMARY KEY,"
                " name TEXT,"
                " version INTEGER NOT NULL)"
            )
        )

        class TempBase(DeclarativeBase):
            pass

        class TempVersionModel(TempBase):
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

        record = (
            db_session.execute(select(TempVersionModel).where(TempVersionModel.id == 1))
            .scalars()
            .first()
        )
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

        record = (
            db_session.execute(select(TempVersionModel).where(TempVersionModel.id == 1))
            .scalars()
            .first()
        )
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

        record = (
            db_session.execute(select(TempVersionModel).where(TempVersionModel.id == 1))
            .scalars()
            .first()
        )
        assert record.name == "newer_version"  # Should be updated.
        assert record.version == 6

    def test_upsert_values_latest_check_column_inclusive(self, db_session):
        """
        Test latest_check_column with >= comparison (inclusive).
        """
        # Create temp table with version column.
        db_session.execute(
            text(
                "CREATE TEMP TABLE test_version_inclusive_temp ("
                " id INTEGER PRIMARY KEY,"
                " name TEXT,"
                " version INTEGER NOT NULL)"
            )
        )

        class TempBase(DeclarativeBase):
            pass

        class TempVersionInclusiveModel(TempBase):
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

        record = (
            db_session.execute(
                select(TempVersionInclusiveModel).where(
                    TempVersionInclusiveModel.id == 1
                )
            )
            .scalars()
            .first()
        )
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

        record = (
            db_session.execute(
                select(TempVersionInclusiveModel).where(
                    TempVersionInclusiveModel.id == 1
                )
            )
            .scalars()
            .first()
        )
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
                "CREATE TEMP TABLE test_version_update_ts_temp ("
                " id INTEGER PRIMARY KEY,"
                " name TEXT,"
                " version INTEGER NOT NULL,"
                " create_ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),"
                " update_ts TIMESTAMPTZ NOT NULL DEFAULT NOW())"
            )
        )

        class TempBase(DeclarativeBase):
            pass

        class TempVersionUpdateTsModel(TempBase):
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

        record = (
            db_session.execute(
                select(TempVersionUpdateTsModel).where(TempVersionUpdateTsModel.id == 1)
            )
            .scalars()
            .first()
        )
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
            db_session.execute(
                select(TempVersionUpdateTsModel).where(TempVersionUpdateTsModel.id == 1)
            )
            .scalars()
            .first()
        )
        assert updated_record.name == "updated"
        assert updated_record.version == 2
        assert (
            updated_record.update_ts > initial_update_ts
        )  # update_ts should be newer.


class TestChunkedUpsert:
    """
    Tests for multi-chunk execution in _upsert_values().

    Uses a tiny chunk_size to force multiple INSERT statements and verifies that rows
    and RETURNING results are aggregated correctly across chunks.
    """

    def test_upsert_all_rows_inserted_across_chunks(self, db_session):
        """
        Test that all rows are inserted when split across chunks.
        """
        values = [{"id": i, "col_a": f"val_{i}"} for i in range(1, 6)]
        _upsert_values(
            model=MyTest,
            values=values,
            session=db_session,
            conflict_columns=["id"],
            on_conflict_update=True,
            chunk_size=2,
        )
        count = db_session.execute(select(func.count()).select_from(MyTest)).scalar()
        assert count == 5

    def test_upsert_returning_aggregated_across_chunks(self, db_session):
        """
        Test that RETURNING results are collected from every chunk.
        """
        values = [{"id": i, "col_a": f"val_{i}"} for i in range(1, 6)]
        results = _upsert_values(
            model=MyTest,
            values=values,
            session=db_session,
            conflict_columns=["id"],
            on_conflict_update=True,
            returning_columns=["id", "col_a"],
            chunk_size=2,
        )
        assert results is not None
        assert len(results) == 5
        returned_ids = sorted(r["id"] for r in results)
        assert returned_ids == [1, 2, 3, 4, 5]

    def test_upsert_updates_existing_across_chunks(self, db_session):
        """
        Test that chunked upsert updates existing rows correctly.
        """
        # Seed rows.
        seed = [{"id": i, "col_a": f"old_{i}"} for i in range(1, 6)]
        _upsert_values(
            model=MyTest,
            values=seed,
            session=db_session,
            conflict_columns=["id"],
            on_conflict_update=True,
        )

        # Upsert with new values in small chunks.
        updated = [{"id": i, "col_a": f"new_{i}"} for i in range(1, 6)]
        _upsert_values(
            model=MyTest,
            values=updated,
            session=db_session,
            conflict_columns=["id"],
            on_conflict_update=True,
            chunk_size=2,
        )
        rows = db_session.execute(select(MyTest).order_by(MyTest.id)).scalars().all()
        assert all(r.col_a == f"new_{r.id}" for r in rows)

    def test_insert_ignore_returning_across_chunks(self, db_session):
        """
        INSERT_IGNORE with `returning_columns` returns one row per input row across
        chunked statements, with existing values preserved for conflicted rows.
        """
        # Seed a subset of rows.
        seed = [{"id": 1, "col_a": "A"}, {"id": 3, "col_a": "C"}]
        _upsert_values(
            model=MyTest,
            values=seed,
            session=db_session,
            conflict_columns=["id"],
            on_conflict_update=True,
        )

        # INSERT_IGNORE with mix of new and existing rows.
        values = [{"id": i, "col_a": f"new_{i}"} for i in range(1, 6)]
        results = _upsert_values(
            model=MyTest,
            values=values,
            session=db_session,
            conflict_columns=["id"],
            on_conflict_update=False,
            returning_columns=["id", "col_a"],
            chunk_size=2,
        )
        assert results is not None
        assert len(results) == 5
        # Position-aligned: result[i] corresponds to input[i] across chunk
        # boundaries. Locks in the no-op DO UPDATE trick's input-order
        # guarantee even when the batch is split.
        assert [r["id"] for r in results] == [1, 2, 3, 4, 5]
        # Existing rows keep their original values; new rows take the input.
        assert [r["col_a"] for r in results] == ["A", "new_2", "C", "new_4", "new_5"]

    def test_plain_insert_across_chunks(self, db_session):
        """
        Test plain INSERT (no conflict) works across chunks.
        """
        values = [{"id": i, "col_a": f"val_{i}"} for i in range(1, 6)]
        _upsert_values(
            model=MyTest,
            values=values,
            session=db_session,
            chunk_size=2,
        )
        count = db_session.execute(select(func.count()).select_from(MyTest)).scalar()
        assert count == 5
