"""
Unit tests for dags.pipelines.garmin.extract module.

This test suite covers:
    - GarminExtractor class functionality.
    - Authentication and error handling.
    - FIT activity file extraction.
    - Garmin data extraction using registry data types.
    - File naming conventions and timestamp generation.
"""

import io
import json
import tempfile
import zipfile

from datetime import date
from pathlib import Path
from unittest.mock import ANY, MagicMock, call, patch

import pendulum
import pytest
from airflow.sdk.exceptions import AirflowSkipException

from dags.lib.etl_config import ETLConfig
from dags.pipelines.garmin.constants import APIMethodTimeParam, GarminDataType
from dags.pipelines.garmin.extract import (
    GarminExtractor,
    extract,
    cli_extract,
    discover_accounts,
)


class TestGarminExtractor:
    """
    Test class for GarminExtractor functionality.
    """

    @pytest.fixture
    def temp_dir(self):
        """
        Create temporary directory for testing.

        :return: Temporary directory path.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)

    @pytest.fixture
    def extractor(self, temp_dir: Path) -> GarminExtractor:
        """
        Create GarminExtractor instance for testing.

        :param temp_dir: Temporary directory fixture.
        :return: GarminExtractor instance.
        """

        return GarminExtractor(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 3),
            ingest_dir=temp_dir,
        )

    @pytest.fixture
    def mock_garmin_client(self) -> MagicMock:
        """
        Create mock Garmin client for testing.

        :return: Mock Garmin client.
        """

        mock_client = MagicMock()
        mock_client.full_name = "Test User"
        mock_client.get_user_profile.return_value = {"id": "123456789"}
        return mock_client

    def test_init(self, temp_dir: Path) -> None:
        """
        Test GarminExtractor initialization.

        :param temp_dir: Temporary directory fixture.
        """

        # Act.
        extractor = GarminExtractor(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 3),
            ingest_dir=temp_dir,
        )

        # Assert.
        assert extractor.start_date == date(2025, 1, 1)
        assert extractor.end_date == date(2025, 1, 3)
        assert extractor.ingest_dir == temp_dir
        assert extractor.garmin_client is None
        assert extractor.user_id is None

    @patch("dags.pipelines.garmin.extract.GarminClient")
    @patch("dags.pipelines.garmin.extract.LOGGER")
    def test_authenticate_success(
        self, mock_logger, mock_garmin_client_class, extractor, mock_garmin_client
    ) -> None:
        """
        Test successful authentication.

        :param mock_logger: Mock logger.
        :param mock_garmin_client_class: Mock GarminClient class.
        :param extractor: GarminExtractor fixture.
        :param mock_garmin_client: Mock GarminClient instance fixture.
        """

        # Arrange.
        mock_garmin_client_class.from_tokens.return_value = mock_garmin_client

        # Act.
        extractor.authenticate("~/.garminconnect/123456789")

        # Assert.
        assert extractor.garmin_client == mock_garmin_client
        assert extractor.user_id == "123456789"
        mock_garmin_client_class.from_tokens.assert_called_once()
        mock_garmin_client.get_user_profile.assert_called_once()
        mock_logger.info.assert_called()

    @patch("dags.pipelines.garmin.extract.GarminClient")
    @patch("dags.pipelines.garmin.extract.LOGGER")
    def test_authenticate_failure(
        self, mock_logger, mock_garmin_client_class, extractor
    ) -> None:
        """
        Test authentication failure.

        :param mock_logger: Mock logger.
        :param mock_garmin_client_class: Mock GarminClient class.
        :param extractor: GarminExtractor fixture.
        """

        # Arrange.
        mock_garmin_client_class.from_tokens.side_effect = Exception("401 Unauthorized")

        # Act & Assert.
        with pytest.raises(RuntimeError, match="Garmin authentication"):
            extractor.authenticate("~/.garminconnect/123456789")

        mock_logger.error.assert_called()

    @patch("dags.pipelines.garmin.extract.LOGGER")
    def test_get_data_types_to_extract_empty_list(self, mock_logger, extractor) -> None:
        """
        Test _get_data_types_to_extract with empty list.

        :param mock_logger: Mock logger.
        :param extractor: GarminExtractor fixture.
        """

        # Act.
        result = extractor._get_data_types_to_extract([])

        # Assert.
        assert result == []
        mock_logger.info.assert_called_once_with("Empty data_types list provided.")

    @patch("dags.pipelines.garmin.extract.LOGGER")
    def test_extract_garmin_data_success(
        self, mock_logger, extractor, mock_garmin_client, temp_dir
    ) -> None:
        """
        Test successful Garmin data extraction.

        :param mock_logger: Mock logger.
        :param extractor: GarminExtractor fixture.
        :param mock_garmin_client: Mock Garmin client fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        extractor.garmin_client = mock_garmin_client
        extractor.user_id = "123456789"

        # Mock registry with a single DAILY data type.
        mock_data_type = GarminDataType(
            name="SLEEP",
            api_method="get_sleep_data",
            api_method_time_param=APIMethodTimeParam.DAILY,
            api_endpoint="/garmin-service/garmin/dailySleepData/{display_name}"
            "?date={date}&nonSleepBufferMinutes=60",
            description="Sleep stage duration",
            emoji="sleep",
        )

        with patch(
            "dags.pipelines.garmin.extract.GARMIN_DATA_REGISTRY"
        ) as mock_registry:
            mock_registry.all_data_types = [mock_data_type]
            mock_garmin_client.get_sleep_data.return_value = {"sleepScores": []}

            # Act.
            result = extractor.extract_garmin_data()

            # Assert.
            assert len(result) == 3  # 3 days of data (inclusive end date).
            mock_garmin_client.get_sleep_data.assert_called()
            mock_logger.info.assert_called()

            # Check files were created.
            files = list(temp_dir.glob("*.json"))
            assert len(files) == 3

    @patch("dags.pipelines.garmin.extract.LOGGER")
    def test_extract_garmin_data_empty_list(self, mock_logger, extractor) -> None:
        """
        Test extract_garmin_data with empty data types list.

        :param mock_logger: Mock logger.
        :param extractor: GarminExtractor fixture.
        """

        # Arrange.
        extractor.data_types = []

        # Act.
        result = extractor.extract_garmin_data()

        # Assert.
        assert result == []
        # Should log both the empty list message from _get_data_types_to_extract
        # and the skipping message from extract_garmin_data
        mock_logger.info.assert_any_call("Empty data_types list provided.")
        mock_logger.info.assert_any_call(
            "Skipping Garmin data extraction: no data types to process."
        )

    @patch("dags.pipelines.garmin.extract.time.sleep")
    @patch("dags.pipelines.garmin.extract.LOGGER")
    def test_extract_data_by_type_daily(
        self, mock_logger, mock_sleep, extractor, mock_garmin_client
    ) -> None:
        """
        Test _extract_data_by_type with DAILY parameter type.

        :param mock_logger: Mock logger.
        :param mock_sleep: Mock sleep function.
        :param extractor: GarminExtractor fixture.
        :param mock_garmin_client: Mock Garmin client fixture.
        """

        # Arrange.
        extractor.garmin_client = mock_garmin_client
        extractor.user_id = "123456789"

        data_type = GarminDataType(
            name="SLEEP",
            api_method="get_sleep_data",
            api_method_time_param=APIMethodTimeParam.DAILY,
            api_endpoint="/garmin-service/garmin/dailySleepData/{display_name}"
            "?date={date}&nonSleepBufferMinutes=60",
            description="Sleep stage duration",
            emoji="sleep",
        )

        mock_garmin_client.get_sleep_data.return_value = {"sleepScores": []}

        # Act.
        result = extractor._extract_data_by_type(
            data_type, date(2025, 1, 1), date(2025, 1, 3)
        )

        # Assert.
        assert len(result) == 3  # 3 days (inclusive end date).
        assert mock_garmin_client.get_sleep_data.call_count == 3
        mock_garmin_client.get_sleep_data.assert_has_calls(
            [call("2025-01-01"), call("2025-01-02"), call("2025-01-03")]
        )
        mock_sleep.assert_called()

    @patch("dags.pipelines.garmin.extract.time.sleep")
    @patch("dags.pipelines.garmin.extract.LOGGER")
    def test_extract_data_by_type_range(
        self, mock_logger, mock_sleep, extractor, mock_garmin_client
    ) -> None:
        """
        Test _extract_data_by_type with RANGE parameter type.

        :param mock_logger: Mock logger.
        :param mock_sleep: Mock sleep function.
        :param extractor: GarminExtractor fixture.
        :param mock_garmin_client: Mock Garmin client fixture.
        """

        # Arrange.
        extractor.garmin_client = mock_garmin_client
        extractor.user_id = "123456789"

        data_type = GarminDataType(
            name="BODY_BATTERY",
            api_method="get_body_battery",
            api_method_time_param=APIMethodTimeParam.RANGE,
            api_endpoint="/garmin-service/garmin/bodyBattery/reports/daily"
            "?startDate={date}&endDate={date}",
            description="Daily summary",
            emoji="battery",
        )

        mock_garmin_client.get_body_battery.return_value = {"data": []}

        # Act.
        result = extractor._extract_data_by_type(
            data_type, date(2025, 1, 1), date(2025, 1, 3)
        )

        # Assert.
        assert len(result) == 3  # 3 days (inclusive end date).
        assert mock_garmin_client.get_body_battery.call_count == 3
        mock_garmin_client.get_body_battery.assert_has_calls(
            [
                call("2025-01-01", "2025-01-01"),
                call("2025-01-02", "2025-01-02"),
                call("2025-01-03", "2025-01-03"),
            ]
        )
        mock_sleep.assert_called()

    @patch("dags.pipelines.garmin.extract.LOGGER")
    def test_extract_data_by_type_no_date(
        self, mock_logger, extractor, mock_garmin_client
    ) -> None:
        """
        Test _extract_data_by_type with NO_DATE parameter type.

        :param mock_logger: Mock logger.
        :param extractor: GarminExtractor fixture.
        :param mock_garmin_client: Mock Garmin client fixture.
        """

        # Arrange.
        extractor.garmin_client = mock_garmin_client
        extractor.user_id = "123456789"

        data_type = GarminDataType(
            name="PERSONAL_RECORDS",
            api_method="get_personal_record",
            api_method_time_param=APIMethodTimeParam.NO_DATE,
            api_endpoint="/personalrecord-service/personalrecord/prs/{display_name}",
            description="All-time personal bests",
            emoji="trophy",
        )

        mock_garmin_client.get_personal_record.return_value = {"records": []}

        # Act.
        result = extractor._extract_data_by_type(
            data_type, date(2025, 1, 1), date(2025, 1, 3)
        )

        # Assert.
        assert len(result) == 1
        mock_garmin_client.get_personal_record.assert_called_once_with()

    def test_save_garmin_data(self, extractor, temp_dir) -> None:
        """
        Test _save_garmin_data method.

        :param extractor: GarminExtractor fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        extractor.user_id = "123456789"
        data = {"sleepScores": [], "date": "2025-01-01"}
        data_type = GarminDataType(
            name="SLEEP",
            api_method="get_sleep_data",
            api_method_time_param=APIMethodTimeParam.DAILY,
            api_endpoint="/garmin-service/garmin/dailySleepData/{display_name}"
            "?date={date}&nonSleepBufferMinutes=60",
            description="Sleep stage duration",
            emoji="sleep",
        )

        with patch("dags.pipelines.garmin.extract.LOGGER") as mock_logger:
            # Act.
            result = extractor._save_garmin_data(data, data_type, date(2025, 1, 1))

            # Assert.
            assert len(result) == 1
            saved_file = result[0]
            assert saved_file.exists()
            assert saved_file.name.startswith("123456789_SLEEP_")
            assert saved_file.name.endswith(".json")

            # Verify file contents.
            with open(saved_file, "r", encoding="utf-8") as f:
                saved_data = json.load(f)
            assert saved_data == data

            mock_logger.info.assert_called()

    @patch("dags.pipelines.garmin.extract.time.sleep")
    @patch("dags.pipelines.garmin.extract.LOGGER")
    def test_extract_fit_activities_success(
        self, mock_logger, mock_sleep, extractor, mock_garmin_client, temp_dir
    ) -> None:
        """
        Test successful FIT activity extraction.

        :param mock_logger: Mock logger.
        :param mock_sleep: Mock sleep function.
        :param extractor: GarminExtractor fixture.
        :param mock_garmin_client: Mock Garmin client fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        extractor.garmin_client = mock_garmin_client
        extractor.user_id = "123456789"

        activities = [
            {
                "activityId": "12345",
                "startTimeGMT": "2025-01-01T10:00:00.000Z",
                "startTimeLocal": "2025-01-01T10:00:00.000",
            },
            {
                "activityId": "67890",
                "startTimeGMT": "2025-01-02T15:30:00.000Z",
                "startTimeLocal": "2025-01-02T15:30:00.000",
            },
        ]
        mock_garmin_client.get_activities_by_date.return_value = activities
        # Create mock ZIP files containing FIT data.
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zip_file:
            zip_file.writestr("12345_ACTIVITY.fit", b"ACTUAL_FIT_FILE_DATA_1")
        zip_buffer.seek(0)
        mock_zip_data_1 = zip_buffer.getvalue()

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zip_file:
            zip_file.writestr("67890_ACTIVITY.fit", b"ACTUAL_FIT_FILE_DATA_2")
        zip_buffer.seek(0)
        mock_zip_data_2 = zip_buffer.getvalue()

        mock_garmin_client.download_activity.side_effect = [
            mock_zip_data_1,
            mock_zip_data_2,
        ]

        # Act.
        result = extractor.extract_fit_activities()

        # Assert.
        assert len(result) == 2
        mock_garmin_client.get_activities_by_date.assert_called_once_with(
            "2025-01-01", "2025-01-03"
        )
        assert mock_garmin_client.download_activity.call_count == 2
        mock_sleep.assert_called()

        # Check files were created and contain extracted FIT data.
        files = list(temp_dir.glob("*.fit"))
        assert len(files) == 2

        # Verify file contents are the extracted FIT data, not ZIP.
        for file_path in files:
            with open(file_path, "rb") as f:
                content = f.read()
                assert b"ACTUAL_FIT_FILE_DATA" in content
                assert not content.startswith(b"PK")  # Not a ZIP file.

    @patch("dags.pipelines.garmin.extract.LOGGER")
    def test_extract_fit_activities_no_activities(
        self, mock_logger, extractor, mock_garmin_client
    ) -> None:
        """
        Test FIT activity extraction with no activities found.

        :param mock_logger: Mock logger.
        :param extractor: GarminExtractor fixture.
        :param mock_garmin_client: Mock Garmin client fixture.
        """

        # Arrange.
        extractor.garmin_client = mock_garmin_client
        mock_garmin_client.get_activities_by_date.return_value = []

        # Act.
        result = extractor.extract_fit_activities()

        # Assert.
        assert result == []
        mock_logger.warning.assert_called_with(
            "No activities found in the specified date range."
        )

    @patch("dags.pipelines.garmin.extract.time.sleep")
    @patch("dags.pipelines.garmin.extract.LOGGER")
    def test_extract_fit_activities_empty_zip(
        self, mock_logger, mock_sleep, extractor, mock_garmin_client, temp_dir
    ) -> None:
        """
        Test FIT activity extraction with empty ZIP archive.

        :param mock_logger: Mock logger.
        :param mock_sleep: Mock sleep function.
        :param extractor: GarminExtractor fixture.
        :param mock_garmin_client: Mock Garmin client fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        extractor.garmin_client = mock_garmin_client
        extractor.user_id = "123456789"

        activities = [
            {
                "activityId": "12345",
                "startTimeGMT": "2025-01-01T10:00:00.000Z",
                "startTimeLocal": "2025-01-01T10:00:00.000",
            }
        ]
        mock_garmin_client.get_activities_by_date.return_value = activities

        # Create an empty ZIP file.
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w"):
            pass  # Empty ZIP.
        zip_buffer.seek(0)
        mock_garmin_client.download_activity.return_value = zip_buffer.getvalue()

        # Act.
        result = extractor.extract_fit_activities()

        # Assert.
        assert len(result) == 0  # No files saved due to empty ZIP.
        mock_logger.warning.assert_called_with(
            "⚠️ Empty ZIP archive for activity 12345."
        )

    @patch("dags.pipelines.garmin.extract.time.sleep")
    @patch("dags.pipelines.garmin.extract.LOGGER")
    def test_extract_fit_activities_non_zip_fallback(
        self, mock_logger, mock_sleep, extractor, mock_garmin_client, temp_dir
    ) -> None:
        """
        Test FIT activity extraction with non-ZIP data (fallback mode).

        :param mock_logger: Mock logger.
        :param mock_sleep: Mock sleep function.
        :param extractor: GarminExtractor fixture.
        :param mock_garmin_client: Mock Garmin client fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        extractor.garmin_client = mock_garmin_client
        extractor.user_id = "123456789"

        activities = [
            {
                "activityId": "12345",
                "startTimeGMT": "2025-01-01T10:00:00.000Z",
                "startTimeLocal": "2025-01-01T10:00:00.000",
            }
        ]
        mock_garmin_client.get_activities_by_date.return_value = activities
        mock_garmin_client.download_activity.return_value = b"RAW_FIT_FILE_DATA"

        # Act.
        result = extractor.extract_fit_activities()

        # Assert.
        assert len(result) == 1

        # Check file was created with raw data (fallback).
        files = list(temp_dir.glob("*.fit"))
        assert len(files) == 1

        with open(files[0], "rb") as f:
            content = f.read()
            assert content == b"RAW_FIT_FILE_DATA"


class TestExtractFunction:
    """
    Test class for the extract function.
    """

    @pytest.fixture
    def mock_config(self, tmp_path) -> ETLConfig:
        """
        Create mock ETL config for testing.

        :param tmp_path: Pytest temporary path fixture.
        :return: Mock ETL config.
        """

        return MagicMock(data_dirs=MagicMock(ingest=tmp_path))

    @patch("dags.pipelines.garmin.extract.discover_accounts")
    @patch("dags.pipelines.garmin.extract.GarminExtractor")
    @patch("dags.pipelines.garmin.extract.LOGGER")
    def test_extract_success(
        self, mock_logger, mock_extractor_class, mock_discover, mock_config
    ) -> None:
        """
        Test successful extract function execution.

        :param mock_logger: Mock logger.
        :param mock_extractor_class: Mock GarminExtractor class.
        :param mock_discover: Mock discover_accounts function.
        :param mock_config: Mock ETL config.
        """

        # Arrange.
        mock_discover.return_value = [("123456789", Path("/fake/token/dir"))]

        mock_extractor = MagicMock()
        mock_extractor.extract_fit_activities.return_value = [Path("activity.fit")]
        mock_extractor.extract_garmin_data.return_value = [Path("data.json")]
        mock_extractor_class.return_value = mock_extractor

        data_interval_start = pendulum.datetime(2025, 1, 1, tz="UTC")
        data_interval_end = pendulum.datetime(2025, 1, 3, tz="UTC")

        # Act.
        extract(mock_config.data_dirs.ingest, data_interval_start, data_interval_end)

        # Assert.
        mock_discover.assert_called_once()
        mock_extractor_class.assert_called_once_with(
            date(2025, 1, 1), date(2025, 1, 2), mock_config.data_dirs.ingest, None
        )
        mock_extractor.authenticate.assert_called_once_with(
            token_store_dir="/fake/token/dir"
        )
        mock_extractor.extract_fit_activities.assert_called_once()
        mock_extractor.extract_garmin_data.assert_called_once()
        mock_logger.info.assert_called()

    @patch("dags.pipelines.garmin.extract.discover_accounts")
    @patch("dags.pipelines.garmin.extract.GarminExtractor")
    def test_extract_same_start_end_date(
        self, mock_extractor_class, mock_discover, mock_config
    ) -> None:
        """
        Test extract function with same start and end date (inclusive logic).

        :param mock_extractor_class: Mock GarminExtractor class.
        :param mock_discover: Mock discover_accounts function.
        :param mock_config: Mock ETL config.
        """

        # Arrange.
        mock_discover.return_value = [("123456789", Path("/fake/token/dir"))]

        mock_extractor = MagicMock()
        mock_extractor.extract_fit_activities.return_value = [Path("activity.fit")]
        mock_extractor.extract_garmin_data.return_value = [Path("data.json")]
        mock_extractor_class.return_value = mock_extractor

        data_interval_start = pendulum.datetime(2025, 1, 1, tz="UTC")
        data_interval_end = pendulum.datetime(2025, 1, 1, tz="UTC")  # Same date

        # Act.
        extract(mock_config.data_dirs.ingest, data_interval_start, data_interval_end)

        # Assert.
        # Should pass the same date (no subtraction) because start_date == end_date
        mock_extractor_class.assert_called_once_with(
            date(2025, 1, 1), date(2025, 1, 1), mock_config.data_dirs.ingest, None
        )

    @patch("dags.pipelines.garmin.extract.discover_accounts")
    @patch("dags.pipelines.garmin.extract.GarminExtractor")
    def test_extract_no_data_found(
        self, mock_extractor_class, mock_discover, mock_config
    ) -> None:
        """
        Test extract function with no data found.

        :param mock_extractor_class: Mock GarminExtractor class.
        :param mock_discover: Mock discover_accounts function.
        :param mock_config: Mock ETL config.
        """

        # Arrange.
        mock_discover.return_value = [("123456789", Path("/fake/token/dir"))]

        mock_extractor = MagicMock()
        mock_extractor.extract_fit_activities.return_value = []
        mock_extractor.extract_garmin_data.return_value = []
        mock_extractor_class.return_value = mock_extractor

        data_interval_start = pendulum.datetime(2025, 1, 1, tz="UTC")
        data_interval_end = pendulum.datetime(2025, 1, 3, tz="UTC")

        # Act & Assert.
        with pytest.raises(AirflowSkipException, match="No Garmin Connect data found"):
            extract(
                mock_config.data_dirs.ingest, data_interval_start, data_interval_end
            )

    @patch("dags.pipelines.garmin.extract.discover_accounts")
    @patch("dags.pipelines.garmin.extract.GarminExtractor")
    def test_extract_activities_false(
        self, mock_extractor_class, mock_discover, mock_config
    ) -> None:
        """
        Test extract function with specific data types (no FIT files).

        :param mock_extractor_class: Mock GarminExtractor class.
        :param mock_discover: Mock discover_accounts function.
        :param mock_config: Mock ETL config.
        """

        # Arrange.
        mock_discover.return_value = [("123456789", Path("/fake/token/dir"))]

        mock_extractor = MagicMock()
        mock_extractor.extract_garmin_data.return_value = [Path("data.json")]
        mock_extractor_class.return_value = mock_extractor

        data_interval_start = pendulum.datetime(2025, 1, 1, tz="UTC")
        data_interval_end = pendulum.datetime(2025, 1, 3, tz="UTC")

        # Act.
        extract(
            mock_config.data_dirs.ingest,
            data_interval_start,
            data_interval_end,
            data_types=["SLEEP"],
        )

        # Assert.
        mock_extractor_class.assert_called_once_with(
            date(2025, 1, 1), date(2025, 1, 2), mock_config.data_dirs.ingest, ["SLEEP"]
        )
        mock_extractor.authenticate.assert_called_once_with(
            token_store_dir="/fake/token/dir"
        )
        mock_extractor.extract_fit_activities.assert_not_called()
        mock_extractor.extract_garmin_data.assert_called_once()

    @patch("dags.pipelines.garmin.extract.discover_accounts")
    @patch("dags.pipelines.garmin.extract.GarminExtractor")
    def test_extract_activities_false_no_garmin_data(
        self, mock_extractor_class, mock_discover, mock_config
    ) -> None:
        """
        Test extract function with specific data types and no Garmin data.

        :param mock_extractor_class: Mock GarminExtractor class.
        :param mock_discover: Mock discover_accounts function.
        :param mock_config: Mock ETL config.
        """

        # Arrange.
        mock_discover.return_value = [("123456789", Path("/fake/token/dir"))]

        mock_extractor = MagicMock()
        mock_extractor.extract_garmin_data.return_value = []
        mock_extractor_class.return_value = mock_extractor

        data_interval_start = pendulum.datetime(2025, 1, 1, tz="UTC")
        data_interval_end = pendulum.datetime(2025, 1, 3, tz="UTC")

        # Act & Assert.
        with pytest.raises(AirflowSkipException, match="No Garmin Connect data found"):
            extract(
                mock_config.data_dirs.ingest,
                data_interval_start,
                data_interval_end,
                data_types=["SLEEP"],  # Specific data type that returns no data
            )

        mock_extractor.extract_fit_activities.assert_not_called()

    @patch("dags.pipelines.garmin.extract.GarminExtractor")
    def test_extract_empty_data_types_list(
        self, mock_extractor_class, mock_config
    ) -> None:
        """
        Test extract function with empty data_types list raises AirflowSkipException.

        :param mock_extractor_class: Mock GarminExtractor class.
        :param mock_config: Mock ETL config.
        """

        # Arrange.
        data_interval_start = pendulum.datetime(2025, 1, 1, tz="UTC")
        data_interval_end = pendulum.datetime(2025, 1, 3, tz="UTC")

        # Act & Assert.
        with pytest.raises(AirflowSkipException) as exc_info:
            extract(
                mock_config.data_dirs.ingest,
                data_interval_start,
                data_interval_end,
                data_types=[],  # Empty list
            )

        # Verify the exception message.
        assert "data_types is an empty list" in str(exc_info.value)
        assert "Use None to extract all types" in str(exc_info.value)

        # Ensure extractor is not even instantiated.
        mock_extractor_class.assert_not_called()

    @patch("dags.pipelines.garmin.extract.GarminExtractor")
    def test_extract_empty_data_types_no_activities(
        self, mock_extractor_class, mock_config
    ) -> None:
        """
        Test extract function with empty data_types.

        :param mock_extractor_class: Mock GarminExtractor class.
        :param mock_config: Mock ETL config.
        """

        # Arrange.
        data_interval_start = pendulum.datetime(2025, 1, 1, tz="UTC")
        data_interval_end = pendulum.datetime(2025, 1, 3, tz="UTC")

        # Act & Assert.
        with pytest.raises(AirflowSkipException, match="data_types is an empty list"):
            extract(
                mock_config.data_dirs.ingest,
                data_interval_start,
                data_interval_end,
                data_types=[],  # Empty list
            )

        # Since validation fails early, extractor should not be created or called.
        mock_extractor_class.assert_not_called()

    @patch("dags.pipelines.garmin.extract.discover_accounts")
    @patch("dags.pipelines.garmin.extract.GarminExtractor")
    @patch("dags.pipelines.garmin.extract.LOGGER")
    def test_extract_with_string_parameters(
        self, mock_logger, mock_extractor_class, mock_discover, mock_config
    ) -> None:
        """
        Test extract function with string date parameters (DAG configuration).

        :param mock_logger: Mock logger.
        :param mock_extractor_class: Mock GarminExtractor class.
        :param mock_discover: Mock discover_accounts function.
        :param mock_config: Mock ETL config.
        """

        # Arrange.
        mock_discover.return_value = [("123456789", Path("/fake/token/dir"))]

        mock_extractor = MagicMock()
        mock_extractor.extract_fit_activities.return_value = [Path("activity.fit")]
        mock_extractor.extract_garmin_data.return_value = [Path("data.json")]
        mock_extractor_class.return_value = mock_extractor

        # Act with string parameters (as provided in DAG configuration).
        extract(
            mock_config.data_dirs.ingest,
            "2015-01-01T00:00:00Z",
            "2015-01-31T23:59:59Z",
        )

        # Assert.
        mock_extractor_class.assert_called_once_with(
            date(2015, 1, 1), date(2015, 1, 30), mock_config.data_dirs.ingest, None
        )
        mock_extractor.authenticate.assert_called_once_with(
            token_store_dir="/fake/token/dir"
        )
        mock_extractor.extract_fit_activities.assert_called_once()
        mock_extractor.extract_garmin_data.assert_called_once()
        mock_logger.info.assert_called()

    @patch("dags.pipelines.garmin.extract.discover_accounts")
    @patch("dags.pipelines.garmin.extract.GarminExtractor")
    @patch("dags.pipelines.garmin.extract.LOGGER")
    def test_extract_exercise_sets_data_type_triggers_fit_extraction(
        self, mock_logger, mock_extractor_class, mock_discover, mock_config
    ) -> None:
        """
        Test that data_types=["EXERCISE_SETS"] triggers extract_fit_activities.

        :param mock_logger: Mock logger.
        :param mock_extractor_class: Mock GarminExtractor class.
        :param mock_discover: Mock discover_accounts function.
        :param mock_config: Mock ETL config.
        """

        # Arrange.
        mock_discover.return_value = [("123456789", Path("/fake/token/dir"))]

        mock_extractor = MagicMock()
        mock_extractor.extract_fit_activities.return_value = [
            Path("activity.fit"),
            Path("exercise_sets.json"),
        ]
        mock_extractor.extract_garmin_data.return_value = []
        mock_extractor_class.return_value = mock_extractor

        data_interval_start = pendulum.datetime(2025, 1, 1, tz="UTC")
        data_interval_end = pendulum.datetime(2025, 1, 3, tz="UTC")

        # Act.
        extract(
            mock_config.data_dirs.ingest,
            data_interval_start,
            data_interval_end,
            data_types=["EXERCISE_SETS"],
        )

        # Assert - extract_fit_activities should be called.
        mock_extractor.extract_fit_activities.assert_called_once()
        mock_extractor.extract_garmin_data.assert_called_once()


class TestCliExtractFunction:
    """
    Test class for the cli_extract function.
    """

    @patch("dags.pipelines.garmin.extract.extract")
    def test_cli_extract_basic(self, mock_extract) -> None:
        """
        Test basic cli_extract function call.

        :param mock_extract: Mock extract function.
        """

        # Act.
        cli_extract("/tmp/test", "2025-01-01", "2025-01-03")

        # Assert.
        mock_extract.assert_called_once()
        _, kwargs = mock_extract.call_args
        assert str(kwargs["ingest_dir"]) == "/tmp/test"
        assert kwargs["data_interval_start"].date() == date(2025, 1, 1)
        assert kwargs["data_interval_end"].date() == date(2025, 1, 3)
        assert kwargs["data_types"] is None
        assert "include_fit" not in kwargs

    @patch("dags.pipelines.garmin.extract.extract")
    def test_cli_extract_with_data_types(self, mock_extract) -> None:
        """
        Test cli_extract function with data types.

        :param mock_extract: Mock extract function.
        """

        # Act.
        cli_extract(
            "/tmp/test",
            "2025-01-01",
            "2025-01-03",
            data_types=["SLEEP", "HRV"],
        )

        # Assert.
        mock_extract.assert_called_once()
        _, kwargs = mock_extract.call_args
        assert kwargs["data_types"] == ["SLEEP", "HRV"]
        assert "include_fit" not in kwargs

    @patch("dags.pipelines.garmin.extract.extract")
    def test_cli_extract_empty_data_types(self, mock_extract) -> None:
        """
        Test cli_extract function with empty data types list.

        :param mock_extract: Mock extract function.
        """

        # Act.
        cli_extract("/tmp/test", "2025-01-01", "2025-01-03", data_types=[])

        # Assert.
        mock_extract.assert_called_once()
        _, kwargs = mock_extract.call_args
        assert kwargs["data_types"] == []

    @patch("dags.pipelines.garmin.extract.extract")
    def test_cli_extract_date_conversion(self, mock_extract) -> None:
        """
        Test cli_extract function date string conversion.

        :param mock_extract: Mock extract function.
        """

        # Act.
        cli_extract("/tmp/test", "2025-12-25", "2025-12-31")

        # Assert.
        mock_extract.assert_called_once()
        _, kwargs = mock_extract.call_args
        assert kwargs["data_interval_start"].date() == date(2025, 12, 25)
        assert kwargs["data_interval_end"].date() == date(2025, 12, 31)
        assert kwargs["data_interval_start"].timezone.name == "UTC"
        assert kwargs["data_interval_end"].timezone.name == "UTC"


class TestExerciseSetsExtraction:
    """
    Test class for exercise sets extraction in strength training activities.
    """

    @pytest.fixture
    def temp_dir(self):
        """
        Create temporary directory for testing.

        :return: Temporary directory path.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)

    @pytest.fixture
    def extractor(self, temp_dir: Path) -> GarminExtractor:
        """
        Create GarminExtractor instance for testing.

        :param temp_dir: Temporary directory fixture.
        :return: GarminExtractor instance.
        """

        return GarminExtractor(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 3),
            ingest_dir=temp_dir,
        )

    @pytest.fixture
    def mock_garmin_client(self) -> MagicMock:
        """
        Create mock Garmin client for testing.

        :return: Mock Garmin client.
        """

        mock_client = MagicMock()
        mock_client.full_name = "Test User"
        return mock_client

    def test_extract_exercise_sets_success(
        self, extractor, mock_garmin_client, temp_dir
    ) -> None:
        """
        Test successful exercise sets extraction.

        :param extractor: GarminExtractor fixture.
        :param mock_garmin_client: Mock Garmin client fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        extractor.garmin_client = mock_garmin_client
        extractor.user_id = "123456789"

        exercise_data = {
            "activityId": 22320029355,
            "exerciseSets": [
                {
                    "messageIndex": 0,
                    "setType": "ACTIVE",
                    "duration": 45.0,
                    "repetitionCount": 10,
                    "weight": 452000.0,
                    "exercises": [
                        {
                            "category": "BENCH_PRESS",
                            "name": "BARBELL_BENCH_PRESS",
                            "probability": 0.98,
                        }
                    ],
                }
            ],
        }
        mock_garmin_client.get_activity_exercise_sets.return_value = exercise_data

        # Act.
        result = extractor._extract_exercise_sets(22320029355, "2025-01-01T12:00:00Z")

        # Assert.
        assert result is not None
        assert result.exists()
        assert "EXERCISE_SETS" in result.name
        assert result.name.endswith(".json")

        # Verify file contents.
        with open(result, "r") as f:
            saved_data = json.load(f)
        assert saved_data["activityId"] == 22320029355
        assert len(saved_data["exerciseSets"]) == 1

    def test_extract_exercise_sets_no_data(self, extractor, mock_garmin_client) -> None:
        """
        Test exercise sets extraction with no data returned.

        :param extractor: GarminExtractor fixture.
        :param mock_garmin_client: Mock Garmin client fixture.
        """

        # Arrange.
        extractor.garmin_client = mock_garmin_client
        extractor.user_id = "123456789"
        mock_garmin_client.get_activity_exercise_sets.return_value = {
            "activityId": 12345,
            "exerciseSets": None,
        }

        # Act.
        result = extractor._extract_exercise_sets(12345, "2025-01-01T12:00:00Z")

        # Assert.
        assert result is None

    def test_extract_exercise_sets_api_error(
        self, extractor, mock_garmin_client
    ) -> None:
        """
        Test exercise sets extraction with API error.

        :param extractor: GarminExtractor fixture.
        :param mock_garmin_client: Mock Garmin client fixture.
        """

        # Arrange.
        extractor.garmin_client = mock_garmin_client
        extractor.user_id = "123456789"
        mock_garmin_client.get_activity_exercise_sets.side_effect = Exception(
            "API error"
        )

        # Act.
        result = extractor._extract_exercise_sets(12345, "2025-01-01T12:00:00Z")

        # Assert.
        assert result is None

    @patch("dags.pipelines.garmin.extract.time.sleep")
    @patch("dags.pipelines.garmin.extract.LOGGER")
    def test_fit_extraction_triggers_exercise_sets(
        self, mock_logger, mock_sleep, extractor, mock_garmin_client, temp_dir
    ) -> None:
        """
        Test that extract_fit_activities fetches exercise sets for strength training
        activities.

        :param mock_logger: Mock logger.
        :param mock_sleep: Mock sleep function.
        :param extractor: GarminExtractor fixture.
        :param mock_garmin_client: Mock Garmin client fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        extractor.garmin_client = mock_garmin_client
        extractor.user_id = "123456789"

        activities = [
            {
                "activityId": "22320029355",
                "startTimeLocal": "2025-01-01T10:00:00.000",
                "activityType": {
                    "typeId": 71,
                    "typeKey": "strength_training",
                },
            },
        ]
        mock_garmin_client.get_activities_by_date.return_value = activities

        # Create mock ZIP file.
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zip_file:
            zip_file.writestr("activity.fit", b"FIT_DATA")
        zip_buffer.seek(0)
        mock_garmin_client.download_activity.return_value = zip_buffer.getvalue()

        # Mock exercise sets API.
        mock_garmin_client.get_activity_exercise_sets.return_value = {
            "activityId": 22320029355,
            "exerciseSets": [
                {"messageIndex": 0, "setType": "ACTIVE"},
            ],
        }

        # Act.
        result = extractor.extract_fit_activities()

        # Assert - both FIT and exercise sets files saved.
        assert len(result) == 2
        mock_garmin_client.get_activity_exercise_sets.assert_called_once_with(
            "22320029355"
        )

        fit_files = list(temp_dir.glob("*.fit"))
        json_files = list(temp_dir.glob("*.json"))
        assert len(fit_files) == 1
        assert len(json_files) == 1
        assert "EXERCISE_SETS" in json_files[0].name

    @patch("dags.pipelines.garmin.extract.time.sleep")
    @patch("dags.pipelines.garmin.extract.LOGGER")
    def test_fit_extraction_skips_exercise_sets_for_running(
        self, mock_logger, mock_sleep, extractor, mock_garmin_client, temp_dir
    ) -> None:
        """
        Test that extract_fit_activities does not fetch exercise sets for non-strength
        activities.

        :param mock_logger: Mock logger.
        :param mock_sleep: Mock sleep function.
        :param extractor: GarminExtractor fixture.
        :param mock_garmin_client: Mock Garmin client fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        extractor.garmin_client = mock_garmin_client
        extractor.user_id = "123456789"

        activities = [
            {
                "activityId": "99999",
                "startTimeLocal": "2025-01-01T10:00:00.000",
                "activityType": {"typeId": 1, "typeKey": "running"},
            },
        ]
        mock_garmin_client.get_activities_by_date.return_value = activities

        # Create mock ZIP file.
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zip_file:
            zip_file.writestr("activity.fit", b"FIT_DATA")
        zip_buffer.seek(0)
        mock_garmin_client.download_activity.return_value = zip_buffer.getvalue()

        # Act.
        result = extractor.extract_fit_activities()

        # Assert - only FIT file, no exercise sets fetch.
        assert len(result) == 1
        mock_garmin_client.get_activity_exercise_sets.assert_not_called()


class TestDiscoverAccounts:
    """
    Test class for the discover_accounts function.
    """

    @pytest.fixture
    def temp_dir(self):
        """
        Create temporary directory for testing.

        :return: Temporary directory path.
        """

        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)

    def test_discover_accounts_single_account(self, temp_dir) -> None:
        """
        Test discover_accounts with a single numeric subdirectory.

        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        account_dir = temp_dir / "12345678"
        account_dir.mkdir()

        # Act.
        result = discover_accounts(str(temp_dir))

        # Assert.
        assert result == [("12345678", account_dir)]

    def test_discover_accounts_multiple_accounts(self, temp_dir) -> None:
        """
        Test discover_accounts with multiple numeric subdirectories returns them sorted.

        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        account_dir_b = temp_dir / "87654321"
        account_dir_b.mkdir()
        account_dir_a = temp_dir / "12345678"
        account_dir_a.mkdir()

        # Act.
        result = discover_accounts(str(temp_dir))

        # Assert.
        assert len(result) == 2
        assert result[0] == ("12345678", account_dir_a)
        assert result[1] == ("87654321", account_dir_b)

    def test_discover_accounts_skips_non_numeric(self, temp_dir) -> None:
        """
        Test discover_accounts ignores non-numeric entries (files and directories).

        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        account_dir = temp_dir / "12345678"
        account_dir.mkdir()
        (temp_dir / "some_file.txt").touch()
        (temp_dir / "not_a_number").mkdir()

        # Act.
        result = discover_accounts(str(temp_dir))

        # Assert.
        assert result == [("12345678", account_dir)]

    def test_discover_accounts_no_base_dir(self) -> None:
        """
        Test discover_accounts raises FileNotFoundError when base dir does not exist.
        """

        # Act & Assert.
        with pytest.raises(FileNotFoundError, match="does not exist"):
            discover_accounts("/nonexistent/path/that/does/not/exist")

    def test_discover_accounts_no_accounts(self, temp_dir) -> None:
        """
        Test discover_accounts raises RuntimeError when base dir exists but is empty.

        :param temp_dir: Temporary directory fixture.
        """

        # Act & Assert.
        with pytest.raises(RuntimeError, match="No account directories found"):
            discover_accounts(str(temp_dir))

    def test_discover_accounts_legacy_layout(self, temp_dir) -> None:
        """
        Test backward compatibility: tokens at root level (no subdirectories) returns
        a single legacy account entry pointing to the base directory.

        :param temp_dir: Temporary directory fixture.
        """

        # Arrange: create token files at root level (pre-multi-account layout).
        (temp_dir / "oauth1_token.json").touch()
        (temp_dir / "oauth2_token.json").touch()

        # Act.
        result = discover_accounts(str(temp_dir))

        # Assert: single account with "legacy" placeholder and base dir as token path.
        assert result == [("legacy", temp_dir)]

    def test_discover_accounts_not_a_directory(self, temp_dir) -> None:
        """
        Test discover_accounts raises NotADirectoryError when path is a file.

        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        file_path = temp_dir / "not_a_dir"
        file_path.touch()

        # Act & Assert.
        with pytest.raises(NotADirectoryError, match="not a directory"):
            discover_accounts(str(file_path))


class TestExtractMultiAccount:
    """
    Test class for multi-account extraction behavior in the extract function.
    """

    @pytest.fixture
    def mock_config(self, tmp_path) -> ETLConfig:
        """
        Create mock ETL config for testing.

        :param tmp_path: Pytest temporary path fixture.
        :return: Mock ETL config.
        """

        return MagicMock(data_dirs=MagicMock(ingest=tmp_path))

    @patch("dags.pipelines.garmin.extract.discover_accounts")
    @patch("dags.pipelines.garmin.extract.GarminExtractor")
    @patch("dags.pipelines.garmin.extract.LOGGER")
    def test_extract_multi_account_success(
        self, mock_logger, mock_extractor_class, mock_discover, mock_config
    ) -> None:
        """
        Test extract with multiple accounts creates an extractor per account and
        extracts data from both.

        :param mock_logger: Mock logger.
        :param mock_extractor_class: Mock GarminExtractor class.
        :param mock_discover: Mock discover_accounts function.
        :param mock_config: Mock ETL config.
        """

        # Arrange.
        mock_discover.return_value = [
            ("12345678", Path("/tokens/12345678")),
            ("87654321", Path("/tokens/87654321")),
        ]

        mock_extractor_1 = MagicMock()
        mock_extractor_1.extract_garmin_data.return_value = [Path("data_1.json")]
        mock_extractor_1.extract_fit_activities.return_value = [Path("activity_1.fit")]

        mock_extractor_2 = MagicMock()
        mock_extractor_2.extract_garmin_data.return_value = [Path("data_2.json")]
        mock_extractor_2.extract_fit_activities.return_value = [Path("activity_2.fit")]

        mock_extractor_class.side_effect = [mock_extractor_1, mock_extractor_2]

        data_interval_start = pendulum.datetime(2025, 1, 1, tz="UTC")
        data_interval_end = pendulum.datetime(2025, 1, 3, tz="UTC")

        # Act.
        extract(mock_config.data_dirs.ingest, data_interval_start, data_interval_end)

        # Assert.
        assert mock_extractor_class.call_count == 2
        mock_extractor_1.authenticate.assert_called_once_with(
            token_store_dir="/tokens/12345678"
        )
        mock_extractor_2.authenticate.assert_called_once_with(
            token_store_dir="/tokens/87654321"
        )
        mock_extractor_1.extract_garmin_data.assert_called_once()
        mock_extractor_2.extract_garmin_data.assert_called_once()
        mock_extractor_1.extract_fit_activities.assert_called_once()
        mock_extractor_2.extract_fit_activities.assert_called_once()

    @patch("dags.pipelines.garmin.extract.discover_accounts")
    @patch("dags.pipelines.garmin.extract.GarminExtractor")
    @patch("dags.pipelines.garmin.extract.LOGGER")
    def test_extract_account_filter(
        self, mock_logger, mock_extractor_class, mock_discover, mock_config
    ) -> None:
        """
        Test extract with account filter only extracts for matching accounts.

        :param mock_logger: Mock logger.
        :param mock_extractor_class: Mock GarminExtractor class.
        :param mock_discover: Mock discover_accounts function.
        :param mock_config: Mock ETL config.
        """

        # Arrange.
        mock_discover.return_value = [
            ("12345678", Path("/tokens/12345678")),
            ("87654321", Path("/tokens/87654321")),
        ]

        mock_extractor = MagicMock()
        mock_extractor.extract_garmin_data.return_value = [Path("data.json")]
        mock_extractor.extract_fit_activities.return_value = [Path("activity.fit")]
        mock_extractor_class.return_value = mock_extractor

        # Simulate dag_run.conf with account filter.
        mock_dag_run = MagicMock()
        mock_dag_run.conf = {"accounts": ["12345678"]}
        mock_task = MagicMock()
        mock_task.task_id = "extract"

        data_interval_start = pendulum.datetime(2025, 1, 1, tz="UTC")
        data_interval_end = pendulum.datetime(2025, 1, 3, tz="UTC")

        # Act.
        extract(
            mock_config.data_dirs.ingest,
            data_interval_start,
            data_interval_end,
            dag_run=mock_dag_run,
            task=mock_task,
        )

        # Assert: only one extractor created (filtered to 12345678 only).
        mock_extractor_class.assert_called_once()
        mock_extractor.authenticate.assert_called_once_with(
            token_store_dir="/tokens/12345678"
        )

    @patch("dags.pipelines.garmin.extract.discover_accounts")
    @patch("dags.pipelines.garmin.extract.GarminExtractor")
    @patch("dags.pipelines.garmin.extract.LOGGER")
    def test_extract_account_filter_string_raises(
        self, mock_logger, mock_extractor_class, mock_discover, mock_config
    ) -> None:
        """
        Test that passing a string for 'accounts' raises ValueError instead of silently
        iterating character-by-character.

        :param mock_logger: Mock logger.
        :param mock_extractor_class: Mock GarminExtractor class.
        :param mock_discover: Mock discover_accounts function.
        :param mock_config: Mock ETL config.
        """

        # Arrange.
        mock_discover.return_value = [
            ("12345678", Path("/tokens/12345678")),
        ]

        mock_dag_run = MagicMock()
        mock_dag_run.conf = {"accounts": "12345678"}
        mock_task = MagicMock()
        mock_task.task_id = "extract"

        data_interval_start = pendulum.datetime(2025, 1, 1, tz="UTC")
        data_interval_end = pendulum.datetime(2025, 1, 3, tz="UTC")

        # Act & Assert.
        with pytest.raises(ValueError, match="must be a list"):
            extract(
                mock_config.data_dirs.ingest,
                data_interval_start,
                data_interval_end,
                dag_run=mock_dag_run,
                task=mock_task,
            )

    @patch("dags.pipelines.garmin.extract.discover_accounts")
    @patch("dags.pipelines.garmin.extract.GarminExtractor")
    @patch("dags.pipelines.garmin.extract.LOGGER")
    def test_extract_data_types_filter(
        self, mock_logger, mock_extractor_class, mock_discover, mock_config
    ) -> None:
        """
        Test extract with data_types filter from dag_run.conf passes the filter to
        GarminExtractor.

        :param mock_logger: Mock logger.
        :param mock_extractor_class: Mock GarminExtractor class.
        :param mock_discover: Mock discover_accounts function.
        :param mock_config: Mock ETL config.
        """

        # Arrange.
        mock_discover.return_value = [
            ("12345678", Path("/tokens/12345678")),
        ]

        mock_extractor = MagicMock()
        mock_extractor.extract_garmin_data.return_value = [Path("data.json")]
        mock_extractor.extract_fit_activities.return_value = []
        mock_extractor_class.return_value = mock_extractor

        mock_dag_run = MagicMock()
        mock_dag_run.conf = {"data_types": ["SLEEP", "HEART_RATE"]}
        mock_task = MagicMock()
        mock_task.task_id = "extract"

        data_interval_start = pendulum.datetime(2025, 1, 1, tz="UTC")
        data_interval_end = pendulum.datetime(2025, 1, 3, tz="UTC")

        # Act.
        extract(
            mock_config.data_dirs.ingest,
            data_interval_start,
            data_interval_end,
            dag_run=mock_dag_run,
            task=mock_task,
        )

        # Assert: data_types filter passed to GarminExtractor.
        mock_extractor_class.assert_called_once_with(
            ANY, ANY, ANY, ["SLEEP", "HEART_RATE"]
        )

    @patch("dags.pipelines.garmin.extract.discover_accounts")
    @patch("dags.pipelines.garmin.extract.GarminExtractor")
    @patch("dags.pipelines.garmin.extract.LOGGER")
    def test_extract_data_types_filter_string_raises(
        self, mock_logger, mock_extractor_class, mock_discover, mock_config
    ) -> None:
        """
        Test that passing a string for 'data_types' in dag_run.conf raises ValueError
        instead of silently iterating character-by-character.

        :param mock_logger: Mock logger.
        :param mock_extractor_class: Mock GarminExtractor class.
        :param mock_discover: Mock discover_accounts function.
        :param mock_config: Mock ETL config.
        """

        # Arrange.
        mock_discover.return_value = [
            ("12345678", Path("/tokens/12345678")),
        ]

        mock_dag_run = MagicMock()
        mock_dag_run.conf = {"data_types": "SLEEP"}
        mock_task = MagicMock()
        mock_task.task_id = "extract"

        data_interval_start = pendulum.datetime(2025, 1, 1, tz="UTC")
        data_interval_end = pendulum.datetime(2025, 1, 3, tz="UTC")

        # Act & Assert.
        with pytest.raises(ValueError, match="must be a list"):
            extract(
                mock_config.data_dirs.ingest,
                data_interval_start,
                data_interval_end,
                dag_run=mock_dag_run,
                task=mock_task,
            )

    @patch("dags.pipelines.garmin.extract.discover_accounts")
    @patch("dags.pipelines.garmin.extract.GarminExtractor")
    @patch("dags.pipelines.garmin.extract.LOGGER")
    def test_extract_data_types_filter_empty_list_skips(
        self, mock_logger, mock_extractor_class, mock_discover, mock_config
    ) -> None:
        """
        Test that passing an empty list for 'data_types' in dag_run.conf raises
        AirflowSkipException.

        :param mock_logger: Mock logger.
        :param mock_extractor_class: Mock GarminExtractor class.
        :param mock_discover: Mock discover_accounts function.
        :param mock_config: Mock ETL config.
        """

        # Arrange.
        mock_discover.return_value = [
            ("12345678", Path("/tokens/12345678")),
        ]

        mock_dag_run = MagicMock()
        mock_dag_run.conf = {"data_types": []}
        mock_task = MagicMock()
        mock_task.task_id = "extract"

        data_interval_start = pendulum.datetime(2025, 1, 1, tz="UTC")
        data_interval_end = pendulum.datetime(2025, 1, 3, tz="UTC")

        # Act & Assert.
        with pytest.raises(AirflowSkipException, match="empty list"):
            extract(
                mock_config.data_dirs.ingest,
                data_interval_start,
                data_interval_end,
                dag_run=mock_dag_run,
                task=mock_task,
            )

    @patch("dags.pipelines.garmin.extract.discover_accounts")
    @patch("dags.pipelines.garmin.extract.GarminExtractor")
    @patch("dags.pipelines.garmin.extract.LOGGER")
    def test_extract_error_isolation(
        self, mock_logger, mock_extractor_class, mock_discover, mock_config
    ) -> None:
        """
        Test that one account failing does not block extraction for other accounts. When
        one account raises an exception but another succeeds, the extract function
        should not raise AirflowSkipException.

        :param mock_logger: Mock logger.
        :param mock_extractor_class: Mock GarminExtractor class.
        :param mock_discover: Mock discover_accounts function.
        :param mock_config: Mock ETL config.
        """

        # Arrange.
        mock_discover.return_value = [
            ("12345678", Path("/tokens/12345678")),
            ("87654321", Path("/tokens/87654321")),
        ]

        # First extractor raises an exception during authentication.
        mock_extractor_fail = MagicMock()
        mock_extractor_fail.authenticate.side_effect = RuntimeError(
            "Authentication failed"
        )

        # Second extractor succeeds.
        mock_extractor_ok = MagicMock()
        mock_extractor_ok.extract_garmin_data.return_value = [Path("data.json")]
        mock_extractor_ok.extract_fit_activities.return_value = [Path("activity.fit")]

        mock_extractor_class.side_effect = [mock_extractor_fail, mock_extractor_ok]

        data_interval_start = pendulum.datetime(2025, 1, 1, tz="UTC")
        data_interval_end = pendulum.datetime(2025, 1, 3, tz="UTC")

        # Act: should not raise because second account produced data.
        extract(mock_config.data_dirs.ingest, data_interval_start, data_interval_end)

        # Assert.
        assert mock_extractor_class.call_count == 2
        mock_extractor_ok.extract_garmin_data.assert_called_once()
        mock_extractor_ok.extract_fit_activities.assert_called_once()
        mock_logger.error.assert_called()  # Error logged for first account.

    @patch("dags.pipelines.garmin.extract.discover_accounts")
    @patch("dags.pipelines.garmin.extract.GarminExtractor")
    @patch("dags.pipelines.garmin.extract.LOGGER")
    def test_extract_all_accounts_fail(
        self, mock_logger, mock_extractor_class, mock_discover, mock_config
    ) -> None:
        """
        Test that AirflowSkipException is raised when all accounts fail to produce data.

        :param mock_logger: Mock logger.
        :param mock_extractor_class: Mock GarminExtractor class.
        :param mock_discover: Mock discover_accounts function.
        :param mock_config: Mock ETL config.
        """

        # Arrange.
        mock_discover.return_value = [
            ("12345678", Path("/tokens/12345678")),
            ("87654321", Path("/tokens/87654321")),
        ]

        # Both extractors raise exceptions.
        mock_extractor_1 = MagicMock()
        mock_extractor_1.authenticate.side_effect = RuntimeError("Auth failed 1")

        mock_extractor_2 = MagicMock()
        mock_extractor_2.authenticate.side_effect = RuntimeError("Auth failed 2")

        mock_extractor_class.side_effect = [mock_extractor_1, mock_extractor_2]

        data_interval_start = pendulum.datetime(2025, 1, 1, tz="UTC")
        data_interval_end = pendulum.datetime(2025, 1, 3, tz="UTC")

        # Act & Assert.
        with pytest.raises(AirflowSkipException, match="No Garmin Connect data found"):
            extract(
                mock_config.data_dirs.ingest, data_interval_start, data_interval_end
            )
