"""
Unit tests for dags.lib.etl_monitor_utils module.
"""

from datetime import datetime
from unittest.mock import patch, MagicMock

import pytest

from dags.lib.etl_monitor_utils import ETLResult, ETLResultRecord


class DummyConfig:
    """
    Dummy ETL configuration class for testing purposes.
    """

    dag_id = "test_dag"
    postgres_user = "test_user"


@pytest.fixture(scope="function")
def dummy_etl_result() -> ETLResult:
    """
    Fixture to create a basic ETLResult object.
    """

    config = DummyConfig()
    dag_start_date = datetime(2025, 8, 1, 12, 0, 0)
    dag_run_id = "run_123"
    with patch("dags.lib.etl_monitor_utils.get_lens_engine", return_value=MagicMock()):
        etl_result = ETLResult(config, dag_start_date, dag_run_id)
    return etl_result


def test_etl_result_record_fields() -> None:
    """
    Test ETLResultRecord field assignment.
    """

    record = ETLResultRecord(
        file_name="file.csv",
        success=True,
        error_type=None,
        traceback=None,
    )
    assert record.file_name == "file.csv"
    assert record.success is True
    assert record.error_type is None
    assert record.traceback is None


def test_set_result_record(dummy_etl_result: ETLResult) -> None:
    """
    Test setting a result record in ETLResult.
    """

    etl_result = dummy_etl_result
    etl_result.set_result_record("file.csv", True)
    assert "file.csv" in etl_result.result_records
    assert etl_result.result_records["file.csv"].success is True


def test_successes_and_errors(dummy_etl_result: ETLResult) -> None:
    """
    Test successes and errors properties of ETLResult.
    """

    etl_result = dummy_etl_result
    etl_result.set_result_record("file1.csv", True)
    etl_result.set_result_record(
        "file2.csv",
        False,
        error_type="ERR",
        traceback="trace",
    )
    successes = etl_result.successes
    errors = etl_result.errors
    assert len(successes) == 1
    assert successes[0].file_name == "file1.csv"
    assert len(errors) == 1
    assert errors[0].file_name == "file2.csv"
    assert errors[0].error_type == "ERR"
    assert errors[0].traceback == "trace"


@patch("dags.lib.etl_monitor_utils.get_lens_engine", return_value=MagicMock())
def test_etl_result_equality(
    mock_engine: MagicMock, dummy_etl_result: ETLResult
) -> None:
    """
    Test ETLResult equality comparison.
    """

    etl_result1 = dummy_etl_result
    etl_result2 = ETLResult(
        etl_result1.config,
        etl_result1.dag_start_date,
        etl_result1.dag_run_id,
    )
    etl_result1.set_result_record("file.csv", True)
    etl_result2.set_result_record("file.csv", True)
    assert etl_result1 == etl_result2
    etl_result2.set_result_record("file2.csv", False)
    assert etl_result1 != etl_result2


def test_submit_writes_to_database(etl_result_session: object) -> None:
    """
    Test that submit() writes ETL results to the database.
    """

    from dags.lib.etl_monitor_utils import ETLResultSqla

    config = DummyConfig()
    dag_start_date = datetime(2025, 8, 1, 12, 0, 0)
    dag_run_id = "run_123"

    # Create ETLResult with real database engine.
    with patch(
        "dags.lib.etl_monitor_utils.get_lens_engine",
        return_value=etl_result_session.get_bind(),
    ):
        etl_result = ETLResult(config, dag_start_date, dag_run_id)
        etl_result.set_result_record("file.csv", True)
        etl_result.set_result_record(
            "file2.csv", False, error_type="ERR", traceback="stack trace"
        )

        # Submit to database.
        etl_result.submit()

    # Query database to verify records were written.
    results = (
        etl_result_session.query(ETLResultSqla)
        .filter(
            ETLResultSqla.dag_id == config.dag_id,
            ETLResultSqla.dag_run_id == dag_run_id,
        )
        .all()
    )

    assert len(results) == 2
    file_names = {r.file_name for r in results}
    assert file_names == {"file.csv", "file2.csv"}

    # Verify success record.
    success_record = next(r for r in results if r.file_name == "file.csv")
    assert success_record.success is True
    assert success_record.error_type is None

    # Verify error record.
    error_record = next(r for r in results if r.file_name == "file2.csv")
    assert error_record.success is False
    assert error_record.error_type == "ERR"
    assert error_record.traceback == "stack trace"
