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


def test_etl_result_record_fields(etl_result_session: object) -> None:
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


def test_set_result_record(
    dummy_etl_result: ETLResult, etl_result_session: object
) -> None:
    """
    Test setting a result record in ETLResult.
    """

    etl_result = dummy_etl_result
    etl_result.set_result_record("file.csv", True)
    assert "file.csv" in etl_result.result_records
    assert etl_result.result_records["file.csv"].success is True


def test_successes_and_errors(
    dummy_etl_result: ETLResult, etl_result_session: object
) -> None:
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


def test_etl_result_equality(
    dummy_etl_result: ETLResult, etl_result_session: object
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


def test_submit_calls_upsert_model_instances(
    dummy_etl_result: ETLResult, etl_result_session: object
) -> None:
    """
    Test that submit calls upsert_model_instances and commits.
    """

    etl_result = dummy_etl_result
    etl_result.set_result_record("file.csv", True)
    with patch(
        "dags.lib.etl_monitor_utils.upsert_model_instances"
    ) as upsert_mock, patch("dags.lib.etl_monitor_utils.Session") as session_mock:
        sess_instance = MagicMock()
        session_mock.return_value.__enter__.return_value = sess_instance
        etl_result.submit()
        upsert_mock.assert_called_once()
        sess_instance.commit.assert_called_once()
