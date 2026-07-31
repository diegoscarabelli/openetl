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

from datetime import date, timedelta
from pathlib import Path
from unittest.mock import ANY, MagicMock, call, patch

import pendulum
import pytest
from airflow.sdk.exceptions import AirflowFailException, AirflowSkipException

from dags.lib.etl_config import ETLConfig
from dags.pipelines.garmin.constants import (
    APIMethodTimeParam,
    GARMIN_DATA_REGISTRY,
    GarminDataType,
)
from dags.pipelines.garmin.extract import (
    GarminExtractor,
    _RETROACTIVE_LOOKBACK_DAYS,
    _retroactive_lookback_start,
    extract,
    cli_extract,
    discover_accounts,
)


class TestRetroactiveLookback:
    """
    Tests for the retroactive-edit lookback (ports garmin-health-data#75).

    Some DAILY types have already-extracted past days that change when the user edits
    history in Garmin Connect (e.g. moving a menstrual period start recomputes
    ``dayInCycle`` for every following day). Those days fall outside the narrow
    incremental window, so the extractor extends the start back a fixed lookback to re-
    fetch and overwrite them.
    """

    def test_extends_recent_start_back_to_lookback_window(self) -> None:
        """
        For a registered type (MENSTRUAL_CYCLE_DAY, 90 days), a recent start is pulled
        back to ``end_date - 90`` so retroactively-recomputed past days are re-fetched.
        """
        menstrual_day = GARMIN_DATA_REGISTRY.get_by_name("MENSTRUAL_CYCLE_DAY")
        end = date(2026, 4, 30)
        effective = _retroactive_lookback_start(menstrual_day, date(2026, 4, 28), end)
        assert effective == end - timedelta(days=90)

    def test_does_not_shrink_an_already_older_start(self) -> None:
        """
        A start already earlier than ``end - lookback`` (e.g. an explicit full-history
        backfill) is left untouched: the lookback only ever moves the start earlier.
        """
        menstrual_day = GARMIN_DATA_REGISTRY.get_by_name("MENSTRUAL_CYCLE_DAY")
        end = date(2026, 4, 30)
        old_start = date(2025, 1, 1)  # Far older than end - 90 days.
        effective = _retroactive_lookback_start(menstrual_day, old_start, end)
        assert effective == old_start

    def test_noop_for_unregistered_type(self) -> None:
        """
        A DAILY type with no retroactive-lookback registration (e.g. SLEEP) is returned
        unchanged.
        """
        sleep = GARMIN_DATA_REGISTRY.get_by_name("SLEEP")
        start = date(2026, 4, 28)
        assert _retroactive_lookback_start(sleep, start, date(2026, 4, 30)) == start

    def test_menstrual_cycle_day_registered_with_90_days(self) -> None:
        """
        MENSTRUAL_CYCLE_DAY is registered with a 90-day retroactive lookback (one full
        cycle's worth of cascade).
        """
        assert _RETROACTIVE_LOOKBACK_DAYS.get("MENSTRUAL_CYCLE_DAY") == 90

    def test_daily_dispatch_applies_lookback(self, tmp_path: Path) -> None:
        """
        ``_extract_data_by_type`` for a registered DAILY type calls
        ``_extract_day_by_day`` with the lookback-extended start, not the raw
        incremental start.
        """
        extractor = GarminExtractor(
            start_date=date(2026, 4, 28),
            end_date=date(2026, 4, 30),
            ingest_dir=tmp_path,
        )
        extractor._extract_day_by_day = MagicMock(return_value=[])
        menstrual_day = GARMIN_DATA_REGISTRY.get_by_name("MENSTRUAL_CYCLE_DAY")
        end = date(2026, 4, 30)

        extractor._extract_data_by_type(menstrual_day, date(2026, 4, 28), end)

        extractor._extract_day_by_day.assert_called_once_with(
            menstrual_day, end - timedelta(days=90), end
        )

    def test_daily_dispatch_no_lookback_for_unregistered_type(
        self, tmp_path: Path
    ) -> None:
        """
        A DAILY type without a registration is dispatched with its original start.
        """
        extractor = GarminExtractor(
            start_date=date(2026, 4, 28),
            end_date=date(2026, 4, 30),
            ingest_dir=tmp_path,
        )
        extractor._extract_day_by_day = MagicMock(return_value=[])
        sleep = GARMIN_DATA_REGISTRY.get_by_name("SLEEP")

        extractor._extract_data_by_type(sleep, date(2026, 4, 28), date(2026, 4, 30))

        extractor._extract_day_by_day.assert_called_once_with(
            sleep, date(2026, 4, 28), date(2026, 4, 30)
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

    @patch("dags.pipelines.garmin.extract.LOGGER")
    def test_extract_data_by_type_range(
        self, mock_logger, extractor, mock_garmin_client
    ) -> None:
        """
        Test _extract_data_by_type with RANGE parameter type.

        Post-port (PR #65), RANGE types issue ONE API call covering the full window (not
        one per day). For unsplittable RANGE types (anything not BODY_COMPOSITION or
        ACTIVITIES_LIST), the response is written as a single file stamped with
        end_date. The synthetic BODY_BATTERY type used here exercises that path.

        :param mock_logger: Mock logger.
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

        mock_garmin_client.get_body_battery.return_value = {"data": [{"x": 1}]}

        # Act.
        result = extractor._extract_data_by_type(
            data_type, date(2025, 1, 1), date(2025, 1, 3)
        )

        # Assert.
        # One API call for the full window (the perf win), and one file stamped with
        # end_date for the unsplittable RANGE type.
        assert len(result) == 1
        mock_garmin_client.get_body_battery.assert_called_once_with(
            "2025-01-01", "2025-01-03"
        )
        assert "2025-01-03" in result[0].name

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

    def test_extract_multisport_children_success(
        self, extractor, mock_garmin_client, temp_dir
    ) -> None:
        """
        A multi-sport parent's legs are fetched via metadataDTO.childIds and saved as
        one MULTISPORT_CHILDREN file wrapping every leg's detail.

        :param extractor: GarminExtractor fixture.
        :param mock_garmin_client: Mock Garmin client fixture.
        :param temp_dir: Temporary directory fixture.
        """
        # Arrange.
        extractor.garmin_client = mock_garmin_client
        extractor.user_id = "123456789"
        mock_garmin_client.get_activity_details.side_effect = [
            {"metadataDTO": {"childIds": [1002, 1003]}},  # Parent detail.
            {"activityId": 1002, "summaryDTO": {"distance": 750.0}},  # Swim leg.
            {"activityId": 1003, "summaryDTO": {"distance": 5000.0}},  # Run leg.
        ]

        # Act.
        result = extractor._extract_multisport_children(1001, "2025-01-01T12:00:00Z")

        # Assert.
        assert result is not None
        assert result.exists()
        assert "MULTISPORT_CHILDREN_1001" in result.name
        with open(result, "r") as f:
            saved = json.load(f)
        assert int(saved["parentActivityId"]) == 1001
        assert [c["activityId"] for c in saved["children"]] == [1002, 1003]

    def test_extract_multisport_children_no_childids(
        self, extractor, mock_garmin_client
    ) -> None:
        """
        A parent whose detail has no ``metadataDTO.childIds`` list produces no file.

        :param extractor: GarminExtractor fixture.
        :param mock_garmin_client: Mock Garmin client fixture.
        """
        # Arrange.
        extractor.garmin_client = mock_garmin_client
        extractor.user_id = "123456789"
        mock_garmin_client.get_activity_details.return_value = {"metadataDTO": {}}

        # Act.
        result = extractor._extract_multisport_children(1001, "2025-01-01T12:00:00Z")

        # Assert.
        assert result is None

    def test_extract_multisport_children_api_error(
        self, extractor, mock_garmin_client
    ) -> None:
        """
        A failure fetching the parent detail is swallowed and yields no file.

        :param extractor: GarminExtractor fixture.
        :param mock_garmin_client: Mock Garmin client fixture.
        """
        # Arrange.
        extractor.garmin_client = mock_garmin_client
        extractor.user_id = "123456789"
        mock_garmin_client.get_activity_details.side_effect = Exception("API error")

        # Act.
        result = extractor._extract_multisport_children(1001, "2025-01-01T12:00:00Z")

        # Assert.
        assert result is None

    @patch("dags.pipelines.garmin.extract.time.sleep")
    @patch("dags.pipelines.garmin.extract.LOGGER")
    def test_fit_extraction_triggers_multisport_children(
        self, mock_logger, mock_sleep, extractor, mock_garmin_client, temp_dir
    ) -> None:
        """
        extract_fit_activities fetches child legs for an activity flagged
        ``parent=True``.

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
                "activityId": "5001",
                "startTimeLocal": "2025-01-01T10:00:00.000",
                "parent": True,
                "activityType": {"typeId": 89, "typeKey": "multi_sport"},
            },
        ]
        mock_garmin_client.get_activities_by_date.return_value = activities

        # Create mock ZIP file for the parent's combined FIT download.
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w") as zip_file:
            zip_file.writestr("activity.fit", b"FIT_DATA")
        zip_buffer.seek(0)
        mock_garmin_client.download_activity.return_value = zip_buffer.getvalue()

        # Parent detail (childIds) then one detail per leg.
        mock_garmin_client.get_activity_details.side_effect = [
            {"metadataDTO": {"childIds": [5002, 5003]}},
            {"activityId": 5002, "summaryDTO": {}},
            {"activityId": 5003, "summaryDTO": {}},
        ]

        # Act.
        result = extractor.extract_fit_activities()

        # Assert - both the FIT file and the MULTISPORT_CHILDREN file are saved.
        assert len(result) == 2
        json_files = list(temp_dir.glob("*MULTISPORT_CHILDREN*.json"))
        assert len(json_files) == 1
        with open(json_files[0], "r") as f:
            saved = json.load(f)
        assert int(saved["parentActivityId"]) == 5001
        assert len(saved["children"]) == 2

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
        Test backward compatibility: tokens at root level (no subdirectories) returns a
        single legacy account entry pointing to the base directory.

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
        Test that one account failing does not block extraction for other accounts.

        When one account raises an exception but another succeeds, the extract function
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
        Test that AirflowFailException is raised when every discovered account hits an
        account-level exception.

        AirflowSkipException would mark the run Success in the UI, hide the failure from
        the operator, and advance prev_data_interval_end_success past the failure window
        — silently losing data and breaking the resume mechanism. AirflowFailException
        keeps the failure visible so the next run auto-backfills the gap.

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
        with pytest.raises(AirflowFailException, match="All 2 Garmin account"):
            extract(
                mock_config.data_dirs.ingest, data_interval_start, data_interval_end
            )


# --------------------------------------------------------------------------------------
# Failure isolation, retries, and ACTIVITIES_LIST disk-read tests
# --------------------------------------------------------------------------------------


class TestRetryHelper:
    """
    Tests for the _with_retries helper.
    """

    def test_with_retries_succeeds_after_transient_failures(self, monkeypatch):
        """
        The helper retries on transient errors and returns the eventual success.
        """
        from dags.pipelines.garmin import extract as extract_mod
        from dags.pipelines.garmin.garmin_client.exceptions import (
            GarminConnectionError,
        )

        monkeypatch.setattr(extract_mod.time, "sleep", lambda _: None)

        fn = MagicMock(
            side_effect=[
                GarminConnectionError("DNS hiccup 1"),
                GarminConnectionError("DNS hiccup 2"),
                {"ok": True},
            ]
        )

        result = extract_mod._with_retries(fn, "arg1", kwarg="value")

        assert result == {"ok": True}
        assert fn.call_count == 3
        fn.assert_called_with("arg1", kwarg="value")

    def test_with_retries_exhausts_and_reraises(self, monkeypatch):
        """
        After exhausting all retries the last transient exception is re-raised.
        """
        from dags.pipelines.garmin import extract as extract_mod
        from dags.pipelines.garmin.garmin_client.exceptions import (
            GarminConnectionError,
        )

        monkeypatch.setattr(extract_mod.time, "sleep", lambda _: None)

        fn = MagicMock(side_effect=GarminConnectionError("persistent failure"))

        with pytest.raises(GarminConnectionError, match="persistent failure"):
            extract_mod._with_retries(fn)

        # 1 initial + 3 retries = 4 total attempts.
        assert fn.call_count == 4

    def test_with_retries_does_not_retry_non_transient(self, monkeypatch):
        """
        Non-transient exceptions (e.g. ValueError) propagate immediately.
        """
        from dags.pipelines.garmin import extract as extract_mod

        monkeypatch.setattr(extract_mod.time, "sleep", lambda _: None)

        fn = MagicMock(side_effect=ValueError("bad input"))

        with pytest.raises(ValueError, match="bad input"):
            extract_mod._with_retries(fn)

        # Only one attempt - no retries for non-transient exceptions.
        assert fn.call_count == 1


class TestExtractionFailureIsolation:
    """
    Tests for the per-date / per-data-type / per-activity isolation layers.
    """

    def test_extract_day_by_day_isolates_per_date_failures(self, tmp_path, monkeypatch):
        """
        A transient API failure on one date does not abort extraction of the rest of the
        date range; the failure is recorded on extractor.failures.
        """
        from dags.pipelines.garmin import extract as extract_mod
        from dags.pipelines.garmin.constants import GARMIN_DATA_REGISTRY

        monkeypatch.setattr(extract_mod.time, "sleep", lambda _: None)

        instance = GarminExtractor(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 3),
            ingest_dir=tmp_path,
            data_types=("SLEEP",),
        )
        instance.user_id = "test-user"

        sleep_type = GARMIN_DATA_REGISTRY.get_by_name("SLEEP")
        # RuntimeError is NOT in _TRANSIENT_API_EXCEPTIONS, so it bypasses
        # the retry loop and is caught by the outer per-date try/except.
        # That's exactly the path we want to exercise here.
        mock_api = MagicMock(
            side_effect=[
                {"value": "ok-day-1"},
                RuntimeError("hiccup"),
                {"value": "ok-day-3"},
            ]
        )
        instance.garmin_client = MagicMock()
        setattr(instance.garmin_client, sleep_type.api_method, mock_api)

        saved = instance._extract_day_by_day(
            sleep_type, date(2025, 1, 1), date(2025, 1, 3)
        )

        # Day1 + day3 succeeded; day2 was recorded as a failure.
        assert len(saved) == 2
        assert mock_api.call_count == 3
        assert any(f.date == "2025-01-02" for f in instance.failures)
        # Failures carry the extractor's user_id for multi-account attribution.
        assert all(f.user_id == "test-user" for f in instance.failures)

    def test_extract_garmin_data_isolates_per_data_type_failures(
        self, tmp_path, monkeypatch
    ):
        """
        A failure inside _extract_data_by_type for one type does not abort the others.
        """
        from dags.pipelines.garmin import extract as extract_mod

        monkeypatch.setattr(extract_mod.time, "sleep", lambda _: None)

        instance = GarminExtractor(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 1),
            ingest_dir=tmp_path,
            data_types=("SLEEP", "HEART_RATE"),
        )
        instance.user_id = "test-user"
        instance.garmin_client = MagicMock()

        fake_path = tmp_path / "fake.json"
        fake_path.write_text("{}")

        def fake_extract(data_type, *_):
            if data_type.name == "SLEEP":
                raise RuntimeError("SLEEP endpoint went away")
            return [fake_path]

        with patch.object(instance, "_extract_data_by_type", side_effect=fake_extract):
            saved = instance.extract_garmin_data()

        assert len(saved) == 1  # HEART_RATE succeeded
        assert any(f.data_type == "SLEEP" for f in instance.failures)

    def test_no_date_api_calls_use_retries(self, tmp_path, monkeypatch):
        """
        NO_DATE data types (USER_PROFILE / PERSONAL_RECORDS / RACE_PREDICTIONS) go
        through _with_retries like DAILY/RANGE types do.
        """
        from dags.pipelines.garmin import extract as extract_mod
        from dags.pipelines.garmin.constants import GARMIN_DATA_REGISTRY
        from dags.pipelines.garmin.garmin_client.exceptions import (
            GarminConnectionError,
        )

        monkeypatch.setattr(extract_mod.time, "sleep", lambda _: None)
        instance = GarminExtractor(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 1),
            ingest_dir=tmp_path,
            data_types=("USER_PROFILE",),
        )
        instance.user_id = "test-user"

        user_profile_type = GARMIN_DATA_REGISTRY.get_by_name("USER_PROFILE")
        mock_api = MagicMock(
            side_effect=[
                GarminConnectionError("DNS hiccup"),
                GarminConnectionError("still flaky"),
                {"id": 12345, "displayName": "test"},
            ]
        )
        instance.garmin_client = MagicMock()
        instance.garmin_client.full_name = "Test User"
        setattr(instance.garmin_client, user_profile_type.api_method, mock_api)

        result = instance._extract_data_by_type(
            user_profile_type, date(2025, 1, 1), date(2025, 1, 1)
        )

        # Two retries then success: 3 attempts, no failure recorded.
        assert mock_api.call_count == 3
        assert len(result) == 1
        assert instance.failures == []


class TestActivitiesListFromDisk:
    """
    Tests for the _load_activities_list_from_disk helper.
    """

    def test_merges_multiple_files_dedupes_by_id(self, tmp_path):
        """
        Multi-day extracts produce one ACTIVITIES_LIST_<date>.json per day.

        The helper must merge all of them and dedupe by activityId.
        """
        instance = GarminExtractor(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 3),
            ingest_dir=tmp_path,
            data_types=("ACTIVITY",),
        )
        instance.user_id = "test-user"
        instance.garmin_client = MagicMock()
        (tmp_path / "test-user_ACTIVITIES_LIST_2025-01-01T12-00-00Z.json").write_text(
            json.dumps([{"activityId": 100, "name": "day1"}])
        )
        (tmp_path / "test-user_ACTIVITIES_LIST_2025-01-02T12-00-00Z.json").write_text(
            json.dumps(
                [
                    {"activityId": 100, "name": "day1-dup"},
                    {"activityId": 200, "name": "day2"},
                ]
            )
        )
        (tmp_path / "test-user_ACTIVITIES_LIST_2025-01-03T12-00-00Z.json").write_text(
            json.dumps([{"activityId": 300, "name": "day3"}])
        )

        result = instance._load_activities_list_from_disk()

        instance.garmin_client.get_activities_by_date.assert_not_called()
        ids = sorted(a["activityId"] for a in result)
        assert ids == [100, 200, 300]

    def test_falls_back_on_corrupt_file(self, tmp_path):
        """
        A single corrupt file returns None so the caller hits the API.
        """
        instance = GarminExtractor(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 2),
            ingest_dir=tmp_path,
            data_types=("ACTIVITY",),
        )
        instance.user_id = "test-user"
        (tmp_path / "test-user_ACTIVITIES_LIST_2025-01-01T12-00-00Z.json").write_text(
            "{not valid json"
        )
        (tmp_path / "test-user_ACTIVITIES_LIST_2025-01-02T12-00-00Z.json").write_text(
            json.dumps([{"activityId": 200}])
        )

        assert instance._load_activities_list_from_disk() is None

    def test_returns_none_when_no_files(self, tmp_path):
        """
        With no matching files the helper returns None (caller falls back).
        """
        instance = GarminExtractor(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 1),
            ingest_dir=tmp_path,
            data_types=("ACTIVITY",),
        )
        instance.user_id = "test-user"
        assert instance._load_activities_list_from_disk() is None

    def test_skips_files_outside_date_window(self, tmp_path):
        """
        Stale ACTIVITIES_LIST files from a previous run with a different window must not
        leak activities into the current extract.
        """
        instance = GarminExtractor(
            start_date=date(2025, 1, 10),
            end_date=date(2025, 1, 12),
            ingest_dir=tmp_path,
            data_types=("ACTIVITY",),
        )
        instance.user_id = "test-user"
        # Stale leftover from a previous run with an earlier window.
        (tmp_path / "test-user_ACTIVITIES_LIST_2025-01-01T12-00-00Z.json").write_text(
            json.dumps([{"activityId": 999, "name": "stale"}])
        )
        # In-window files (full 3-day coverage so the partial-coverage
        # fallback doesn't fire).
        (tmp_path / "test-user_ACTIVITIES_LIST_2025-01-10T12-00-00Z.json").write_text(
            json.dumps([{"activityId": 100, "name": "current"}])
        )
        (tmp_path / "test-user_ACTIVITIES_LIST_2025-01-11T12-00-00Z.json").write_text(
            json.dumps([{"activityId": 150, "name": "current"}])
        )
        (tmp_path / "test-user_ACTIVITIES_LIST_2025-01-12T12-00-00Z.json").write_text(
            json.dumps([{"activityId": 200, "name": "current"}])
        )

        result = instance._load_activities_list_from_disk()

        ids = sorted(a["activityId"] for a in result)
        assert ids == [100, 150, 200]

    def test_returns_none_when_only_out_of_window_files(self, tmp_path):
        """
        If every matching file is outside the window the helper returns None so the
        caller falls back to a fresh API call.
        """
        instance = GarminExtractor(
            start_date=date(2025, 2, 1),
            end_date=date(2025, 2, 3),
            ingest_dir=tmp_path,
            data_types=("ACTIVITY",),
        )
        instance.user_id = "test-user"
        (tmp_path / "test-user_ACTIVITIES_LIST_2025-01-01T12-00-00Z.json").write_text(
            json.dumps([{"activityId": 1}])
        )

        assert instance._load_activities_list_from_disk() is None

    def test_drops_entries_without_activity_id(self, tmp_path):
        """
        Entries that aren't dicts or are missing ``activityId`` must be dropped so
        downstream code can assume every item has an ``activityId``.
        """
        instance = GarminExtractor(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 1),
            ingest_dir=tmp_path,
            data_types=("ACTIVITY",),
        )
        instance.user_id = "test-user"
        (tmp_path / "test-user_ACTIVITIES_LIST_2025-01-01T12-00-00Z.json").write_text(
            json.dumps(
                [
                    {"activityId": 100, "name": "good"},
                    {"name": "missing-id"},
                    "not-a-dict",
                    {"activityId": 200, "name": "good"},
                ]
            )
        )

        result = instance._load_activities_list_from_disk()

        ids = sorted(a["activityId"] for a in result)
        assert ids == [100, 200]

    def test_returns_none_when_disk_coverage_is_partial(self, tmp_path):
        """
        Window has 3 days but only 2 ACTIVITIES_LIST files exist (e.g. day 2 had a
        transient API failure during extract).

        The function must return None to force a fresh API call rather than silently
        using the partial data, otherwise extract_fit_activities would never download
        FITs for the missing day.
        """
        instance = GarminExtractor(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 3),
            ingest_dir=tmp_path,
            data_types=("ACTIVITY",),
        )
        instance.user_id = "test-user"
        # Day 1 + day 3 present; day 2 missing (simulates a per-date
        # ACTIVITIES_LIST failure that recorded a failure record but no file).
        (tmp_path / "test-user_ACTIVITIES_LIST_2025-01-01T12-00-00Z.json").write_text(
            json.dumps([{"activityId": 100}])
        )
        (tmp_path / "test-user_ACTIVITIES_LIST_2025-01-03T12-00-00Z.json").write_text(
            json.dumps([{"activityId": 300}])
        )

        assert instance._load_activities_list_from_disk() is None

    def test_returns_data_when_full_window_covered(self, tmp_path):
        """
        Sanity check: when every day in the window has a file, the helper returns the
        merged data without falling back to the API.
        """
        instance = GarminExtractor(
            start_date=date(2025, 1, 1),
            end_date=date(2025, 1, 2),
            ingest_dir=tmp_path,
            data_types=("ACTIVITY",),
        )
        instance.user_id = "test-user"
        (tmp_path / "test-user_ACTIVITIES_LIST_2025-01-01T12-00-00Z.json").write_text(
            json.dumps([{"activityId": 100}])
        )
        (tmp_path / "test-user_ACTIVITIES_LIST_2025-01-02T12-00-00Z.json").write_text(
            json.dumps([{"activityId": 200}])
        )

        result = instance._load_activities_list_from_disk()
        ids = sorted(a["activityId"] for a in result)
        assert ids == [100, 200]
