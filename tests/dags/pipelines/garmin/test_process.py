"""
Unit tests for dags.pipelines.garmin.process module.

This test suite covers:
    - GarminProcessor class functionality.
    - File processing and data extraction.
    - Sleep data processing (SLEEP and SPO2 files).
    - User profile and activity processing.
    - Database session integration and model creation.
"""

import copy
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List
from unittest.mock import MagicMock, patch

import pytest

from dags.lib.etl_config import ETLConfig
from dags.lib.filesystem_utils import FileSet
from dags.pipelines.garmin.constants import (
    GARMIN_FILE_TYPES,
    PR_TYPE_LABELS,
)
from dags.pipelines.garmin.process import GarminProcessor
from dags.pipelines.garmin.sqla_models import (
    Acclimation,
    Activity,
    BodyBattery,
    BreathingDisruption,
    HeartRate,
    HRV,
    PersonalRecord,
    RacePredictions,
    Respiration,
    Sleep,
    SleepMovement,
    SleepRestlessMoment,
    SpO2,
    Steps,
    Stress,
    TrainingLoad,
    TrainingReadiness,
    User,
    UserProfile,
    VO2Max,
)


# pylint: disable=protected-access,too-many-public-methods
class TestGarminProcessor:
    """
    Test class for GarminProcessor functionality.
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
    def processor(self) -> GarminProcessor:
        """
        Create GarminProcessor instance for testing.

        :return: GarminProcessor instance.
        """

        # Create mock config.
        mock_config = MagicMock(spec=ETLConfig)

        with patch("dags.lib.dag_utils.ETLResult"):
            return GarminProcessor(
                config=mock_config,
                dag_run_id="test_run_123",
                dag_start_date=datetime(2022, 1, 1),
                file_sets=[],
            )

    @pytest.fixture
    def mock_session(self) -> MagicMock:
        """
        Create mock SQLAlchemy session for testing.

        :return: Mock session.
        """

        session = MagicMock()
        session.query.return_value.filter.return_value.first.return_value = None
        session.merge.return_value = None
        session.add.return_value = None
        return session

    @pytest.fixture
    def sample_sleep_data(self) -> Dict[str, any]:
        """
        Create sample sleep data for testing.

        :return: Sample sleep JSON data.
        """

        return {
            "dailySleepDTO": {
                "id": 123456789,
                "sleepStartTimestampGMT": 1640995200000,  # 2022-01-01 00:00:00 UTC
                "sleepEndTimestampGMT": 1641024000000,  # 2022-01-01 08:00:00 UTC
                "sleepStartTimestampLocal": 1640995200000,
                "sleepEndTimestampLocal": 1641024000000,
                "calendarDate": "2022-01-01",
                "sleepTimeSeconds": 28800,
                "deepSleepSeconds": 7200,
                "lightSleepSeconds": 14400,
                "remSleepSeconds": 5400,
                "awakeSleepSeconds": 1800,
                "averageSpO2Value": 94.0,
                "lowestSpO2Value": 91,
                "highestSpO2Value": 98,
                "averageRespirationValue": 15.2,
                "lowestRespirationValue": 12.0,
                "highestRespirationValue": 18.5,
                "sleepScores": {
                    "overall": {"qualifierKey": "GOOD", "value": 85},
                    "deepPercentage": {"qualifierKey": "EXCELLENT", "value": 25},
                    "lightPercentage": {"qualifierKey": "GOOD", "value": 50},
                    "remPercentage": {"qualifierKey": "FAIR", "value": 19},
                },
                "sleepNeed": {
                    "baseline": 28800,
                    "actual": 28800,
                    "feedback": "You got your recommended sleep time.",
                },
                "nextSleepNeed": {
                    "baseline": 28800,
                    "actual": 28800,
                    "feedback": "Aim for 8 hours tonight.",
                },
            },
            "wellnessSpO2SleepSummaryDTO": {
                "numberOfEventsBelowThreshold": 2,
            },
            "sleepMovement": [
                {"startGMT": "2022-01-01T00:30:00Z", "activityLevel": 0.1},
                {"startGMT": "2022-01-01T01:00:00Z", "activityLevel": 0.2},
            ],
            "sleepRestlessMoments": [
                {"startGMT": 1640997000000, "value": 1},  # Epoch milliseconds
                {"startGMT": 1641001200000, "value": 2},
            ],
            "wellnessEpochSPO2DataDTOList": [
                {"epochTimestamp": "2022-01-01T00:00:00Z", "spo2Reading": 97},
                {"epochTimestamp": "2022-01-01T01:00:00Z", "spo2Reading": 96},
            ],
            "hrvData": [
                {"startGMT": 1640995800000, "value": 42.5},  # Epoch milliseconds
                {"startGMT": 1640999400000, "value": 45.2},
            ],
            "breathingDisruptionData": [
                {"startGMT": 1641000000000, "value": 1},  # Epoch milliseconds
                {"startGMT": 1641003600000, "value": 2},
            ],
            "remSleepData": True,
            "restlessMomentsCount": 12,
            "avgOvernightHrv": 43.8,
            "bodyBatteryChange": -25,
        }

    @pytest.fixture
    def sample_user_profile_data(self) -> Dict[str, any]:
        """
        Create sample user profile data for testing.

        :return: Sample user profile JSON data.
        """

        return {
            "full_name": "Test User",
            "userData": {
                "gender": "MALE",
                "weight": 70.5,
                "height": 175.0,
                "birthDate": "1990-01-01",
                "vo2MaxRunning": 55.2,
                "vo2MaxCycling": 62.1,
            },
        }

    @pytest.fixture
    def sample_activity_data(self) -> List[Dict[str, any]]:
        """
        Create sample activity data for testing.

        :return: Sample activity JSON data.
        """

        return [
            {
                "activityId": 987654321,
                "activityName": "Morning Run",
                "activityType": {"typeId": 1, "typeKey": "running"},
                "eventType": {"typeId": 9, "typeKey": "race"},
                "startTimeGMT": "2022-01-01T06:00:00.000",
                "startTimeLocal": "2022-01-01T07:00:00.000",
                "endTimeGMT": "2022-01-01T07:00:00.000",
                "deviceId": 123456,
                "manufacturer": "Garmin",
                "timeZoneId": 1,
                "hasPolyline": True,
                "hasImages": False,
                "hasVideo": False,
                "hasSplits": True,
                "hasHeatMap": False,
                "parent": False,
                "purposeful": True,
                "favorite": False,
                "elevationCorrected": True,
                "atpActivity": False,
                "manualActivity": False,
                "pr": True,
                "autoCalcCalories": True,
                "duration": 3600.0,
                "distance": 10000.0,
                "calories": 600.0,
                "averageHR": 150,
                "maxHR": 175,
                "steps": 12000,
                "vO2MaxValue": 55.5,
            }
        ]

    def test_parse_filename_json_format(self, processor: GarminProcessor) -> None:
        """
        Test _parse_filename with JSON file format.

        :param processor: GarminProcessor fixture.
        """

        # Act.
        result = processor._parse_filename("123456789_SLEEP_2022-01-01T00-00-00Z.json")

        # Assert.
        assert result["user_id"] == "123456789"
        assert result["data_type"] == "SLEEP"
        assert result["timestamp"] == "2022-01-01T00-00-00Z"
        assert result["file_extension"] == "json"

    def test_parse_filename_fit_format(self, processor: GarminProcessor) -> None:
        """
        Test _parse_filename with FIT file format.

        :param processor: GarminProcessor fixture.
        """

        # Act.
        result = processor._parse_filename(
            "123456789_ACTIVITY_987654321_2022-01-01T06-00-00Z.fit"
        )

        # Assert.
        assert result["user_id"] == "123456789"
        assert result["data_type"] == "ACTIVITY"
        assert result["timestamp"] == "2022-01-01T06-00-00Z"
        assert result["file_extension"] == "fit"

    def test_parse_filename_invalid_format(self, processor):
        """
        Test _parse_filename with invalid filename format.

        :param processor: GarminProcessor fixture.
        """

        # Act & Assert.
        with pytest.raises(
            ValueError, match="Filename does not match expected pattern"
        ):
            processor._parse_filename("invalid_filename.json")

    def test_ensure_user_exists_new_user(self, processor, mock_session):
        """
        Test _ensure_user_exists with new user creation.

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        """

        # Arrange.
        mock_session.query.return_value.filter.return_value.first.return_value = None

        # Act.
        processor._ensure_user_exists("123456789", mock_session)

        # Assert.
        mock_session.execute.assert_called_once()
        mock_session.flush.assert_called_once()
        assert processor.must_update_user is True

    def test_ensure_user_exists_existing_user(self, processor, mock_session):
        """
        Test _ensure_user_exists with existing user.

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        """

        # Arrange.
        existing_user = User(user_id=123456789, full_name="Test User")
        mock_session.query.return_value.filter.return_value.first.return_value = (
            existing_user
        )

        # Act.
        processor._ensure_user_exists("123456789", mock_session)

        # Assert.
        mock_session.add.assert_not_called()

    def test_load_json_file(self, processor, temp_dir):
        """
        Test _load_json_file method.

        :param processor: GarminProcessor fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        test_data = {"test": "data"}
        test_file = temp_dir / "test.json"
        with open(test_file, "w", encoding="utf-8") as f:
            json.dump(test_data, f)

        # Act.
        result = processor._load_json_file(test_file)

        # Assert.
        assert result == test_data

    def test_convert_field_name(self, processor):
        """
        Test _convert_field_name static method.

        :param processor: GarminProcessor fixture.
        """

        # Act & Assert.
        assert processor._convert_field_name("camelCase") == "camel_case"
        assert processor._convert_field_name("HTTPResponse") == "h_t_t_p_response"
        assert processor._convert_field_name("simpleword") == "simpleword"
        assert processor._convert_field_name("XMLParser") == "x_m_l_parser"

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_sleep_file(
        self, mock_upsert, processor, mock_session, temp_dir, sample_sleep_data
    ):
        """
        Test _process_sleep method.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        :param sample_sleep_data: Sample sleep data fixture.
        """

        # Configure mock to simulate database behavior: assign IDs to sleep records.
        def mock_upsert_side_effect(**kwargs):
            model_instances = kwargs.get("model_instances", [])
            for i, instance in enumerate(model_instances):
                if hasattr(instance, "sleep_id") and instance.sleep_id is None:
                    instance.sleep_id = 1000 + i  # Simulate auto-generated ID.
            return model_instances

        mock_upsert.side_effect = mock_upsert_side_effect

        # Arrange.
        sleep_file = temp_dir / "123456789_SLEEP_2022-01-01T00-00-00Z.json"
        with open(sleep_file, "w", encoding="utf-8") as f:
            json.dump(sample_sleep_data, f)

        # Act.
        processor.user_id = 1
        processor._process_sleep(sleep_file, mock_session)

        # Assert.
        # Verify upsert was called for sleep base record + timeseries data.
        assert (
            mock_upsert.call_count == 6
        )  # Sleep base + Movement, restless, SpO2, HRV, breathing

        # Check first call is for sleep base record.
        first_call = mock_upsert.call_args_list[0]
        assert first_call[1]["conflict_columns"] == ["user_id", "start_ts"]
        assert first_call[1]["on_conflict_update"] is True
        assert len(first_call[1]["model_instances"]) == 1
        assert isinstance(first_call[1]["model_instances"][0], Sleep)
        assert first_call[1]["model_instances"][0].user_id == 1

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_sleep_base(self, mock_upsert, processor, mock_session):
        """
        Test _process_sleep_base method.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        """

        # Arrange.
        sleep_data = {
            "dailySleepDTO": {
                "sleepStartTimestampGMT": 1641078000000,  # 2022-01-01T22:00:00Z
                "sleepEndTimestampGMT": 1641106800000,  # 2022-01-02T06:00:00Z
                "sleepStartTimestampLocal": 1641052800000,  # 2022-01-01T15:00:00Z
                "sleepTimeSeconds": 28800,
                "calendarDate": "2022-01-01",
            }
        }
        # Mock the return value with a Sleep instance containing sleep_id.
        mock_sleep_with_id = Sleep()
        mock_sleep_with_id.sleep_id = 123456789
        mock_upsert.return_value = [mock_sleep_with_id]

        # Act.
        processor.user_id = 1
        result = processor._process_sleep_base(sleep_data, mock_session)

        # Assert.
        mock_upsert.assert_called_once()
        call_args = mock_upsert.call_args
        assert call_args[1]["session"] == mock_session
        assert call_args[1]["conflict_columns"] == ["user_id", "start_ts"]
        assert call_args[1]["on_conflict_update"] is True
        assert len(call_args[1]["model_instances"]) == 1
        assert isinstance(call_args[1]["model_instances"][0], Sleep)

        # Verify update_columns excludes primary key and conflict columns.
        update_columns = call_args[1]["update_columns"]
        assert "sleep_id" not in update_columns  # Primary key excluded.
        assert "user_id" not in update_columns  # Conflict column excluded.
        assert "start_ts" not in update_columns  # Conflict column excluded.
        # Should include other sleep columns.
        assert "end_ts" in update_columns
        assert "sleep_time_seconds" in update_columns

        # Now the function should return the sleep_id from the persisted instance.
        assert result == 123456789

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_sleep_movement(self, mock_upsert, processor, mock_session):
        """
        Test _process_sleep_movement method.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        """

        # Arrange.
        data = {
            "sleepMovement": [
                {"startGMT": "2022-01-01T00:30:00Z", "activityLevel": 0.1},
                {"startGMT": "2022-01-01T01:00:00Z", "activityLevel": 0.2},
            ]
        }

        # Act.
        processor.user_id = 123456789
        processor._process_sleep_movement(data, 123456, mock_session)

        # Assert.
        mock_upsert.assert_called_once()
        _, kwargs = mock_upsert.call_args
        model_instances = kwargs["model_instances"]
        assert len(model_instances) == 2
        assert all(isinstance(m, SleepMovement) for m in model_instances)
        assert kwargs["conflict_columns"] == ["sleep_id", "timestamp"]
        assert kwargs["on_conflict_update"] is False

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_sleep_restless_moments(self, mock_upsert, processor, mock_session):
        """
        Test _process_sleep_restless_moments method.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        """

        # Arrange.
        data = {
            "sleepRestlessMoments": [
                {"startGMT": 1640997000000, "value": 1},
                {"startGMT": 1641001200000, "value": 2},
            ]
        }

        # Act.
        processor.user_id = 123456789
        processor._process_sleep_restless_moments(data, 123456, mock_session)

        # Assert.
        mock_upsert.assert_called_once()
        _, kwargs = mock_upsert.call_args
        model_instances = kwargs["model_instances"]
        assert len(model_instances) == 2
        assert all(isinstance(m, SleepRestlessMoment) for m in model_instances)
        assert kwargs["conflict_columns"] == ["sleep_id", "timestamp"]
        assert kwargs["on_conflict_update"] is False

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_sleep_spo2_data(self, mock_upsert, processor, mock_session):
        """
        Test _process_sleep_spo2_data method.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        """

        # Arrange.
        data = {
            "wellnessEpochSPO2DataDTOList": [
                {"epochTimestamp": "2022-01-01T00:00:00Z", "spo2Reading": 97},
                {"epochTimestamp": "2022-01-01T01:00:00Z", "spo2Reading": 96},
            ]
        }

        # Act.
        processor.user_id = 123456789
        processor._process_sleep_spo2_data(data, 123456, mock_session)

        # Assert.
        mock_upsert.assert_called_once()
        _, kwargs = mock_upsert.call_args
        model_instances = kwargs["model_instances"]
        assert len(model_instances) == 2
        assert all(isinstance(m, SpO2) for m in model_instances)
        assert kwargs["conflict_columns"] == ["sleep_id", "timestamp"]
        assert kwargs["on_conflict_update"] is False

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_sleep_hrv_data(self, mock_upsert, processor, mock_session):
        """
        Test _process_sleep_hrv_data method.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        """

        # Arrange.
        data = {
            "hrvData": [
                {"startGMT": 1640995800000, "value": 42.5},
                {"startGMT": 1640999400000, "value": 45.2},
            ]
        }

        # Act.
        processor.user_id = 123456789
        processor._process_sleep_hrv_data(data, 123456, mock_session)

        # Assert.
        mock_upsert.assert_called_once()
        _, kwargs = mock_upsert.call_args
        model_instances = kwargs["model_instances"]
        assert len(model_instances) == 2
        assert all(isinstance(m, HRV) for m in model_instances)
        assert kwargs["conflict_columns"] == ["sleep_id", "timestamp"]
        assert kwargs["on_conflict_update"] is False

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_sleep_breathing_disruption(
        self, mock_upsert, processor, mock_session
    ):
        """
        Test _process_sleep_breathing_disruption method.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        """

        # Arrange.
        data = {
            "breathingDisruptionData": [
                {"startGMT": 1641000000000, "value": 1},
                {"startGMT": 1641003600000, "value": 2},
            ]
        }

        # Act.
        processor.user_id = 123456789
        processor._process_sleep_breathing_disruption(data, 123456, mock_session)

        # Assert.
        mock_upsert.assert_called_once()
        _, kwargs = mock_upsert.call_args
        model_instances = kwargs["model_instances"]
        assert len(model_instances) == 2
        assert all(isinstance(m, BreathingDisruption) for m in model_instances)
        assert kwargs["conflict_columns"] == ["sleep_id", "timestamp"]
        assert kwargs["on_conflict_update"] is False

    def test_process_user_profile(
        self, processor, mock_session, temp_dir, sample_user_profile_data
    ):
        """
        Test _process_user_profile method.

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        :param sample_user_profile_data: Sample user profile data fixture.
        """

        # Arrange.
        profile_file = temp_dir / "123456789_USER_PROFILE_2022-01-01T00-00-00Z.json"
        with open(profile_file, "w", encoding="utf-8") as f:
            json.dump(sample_user_profile_data, f)

        # Mock existing user check.
        mock_session.query.return_value.filter.return_value.first.return_value = None

        # Act.
        processor.user_id = 123456789
        processor._process_user_profile(profile_file, mock_session)

        # Assert.
        mock_session.add.assert_called_once()
        added_user = mock_session.add.call_args[0][0]
        assert isinstance(added_user, UserProfile)
        assert added_user.user_id == 123456789
        assert added_user.gender == "male"
        assert added_user.weight == 70.5

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_activities_list(
        self, mock_upsert, processor, mock_session, temp_dir, sample_activity_data
    ):
        """
        Test _process_activities method.

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        :param sample_activity_data: Sample activity data fixture.
        """

        # Arrange.
        activities_file = (
            temp_dir / "123456789_ACTIVITIES_LIST_2022-01-01T00-00-00Z.json"
        )
        with open(activities_file, "w", encoding="utf-8") as f:
            json.dump(sample_activity_data, f)

        # Act.
        processor.user_id = 1
        processor._process_activities(activities_file, mock_session)

        # Assert.
        # Verify upsert was called (activity base + supplemental metrics).
        assert mock_upsert.call_count >= 1

        # Check first call is for activity base record.
        first_call = mock_upsert.call_args_list[0]
        assert first_call[1]["conflict_columns"] == ["activity_id"]
        assert first_call[1]["on_conflict_update"] is True
        assert len(first_call[1]["model_instances"]) == 1
        assert isinstance(first_call[1]["model_instances"][0], Activity)
        assert first_call[1]["model_instances"][0].activity_id == 987654321
        assert first_call[1]["model_instances"][0].activity_name == "Morning Run"

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_activity_base(self, mock_upsert, processor, mock_session):
        """
        Test _process_activity_base method.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        """

        # Arrange.
        activity_data = {
            "activityId": 987654321,
            "activityName": "Morning Run",
            "activityType": {"typeId": 1, "typeKey": "running"},
            "eventType": {"typeId": 1, "typeKey": "other"},
            "startTimeGMT": "2022-01-01T07:00:00",
            "startTimeLocal": "2022-01-01T00:00:00",
            "endTimeGMT": "2022-01-01T08:30:00",
            "deviceId": 123456789,
            "manufacturer": "GARMIN",
            "timeZoneId": 1,
            "parent": False,
            "purposeful": True,
            "favorite": False,
            "pr": False,
            "hasPolyline": True,
            "hasImages": False,
            "hasVideo": False,
            "hasSplits": True,
            "hasHeatMap": False,
            "elevationCorrected": True,
            "atpActivity": False,
            "manualActivity": False,
            "autoCalcCalories": True,
        }

        # Mock the return value with an Activity instance containing activity_id.
        mock_activity_with_id = Activity()
        mock_activity_with_id.activity_id = 987654321
        mock_upsert.return_value = [mock_activity_with_id]

        # Act.
        processor.user_id = 1
        result = processor._process_activity_base(activity_data, mock_session)

        # Assert.
        mock_upsert.assert_called_once()
        call_args = mock_upsert.call_args
        assert call_args[1]["session"] == mock_session
        assert call_args[1]["conflict_columns"] == ["activity_id"]
        assert call_args[1]["on_conflict_update"] is True
        assert len(call_args[1]["model_instances"]) == 1
        assert isinstance(call_args[1]["model_instances"][0], Activity)
        assert result == 987654321  # Should return activity_id.

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_activity_base_preserves_ts_data_available_flag(
        self, mock_upsert, processor, mock_session
    ):
        """
        Test that _process_activity_base excludes ts_data_available from updates.

        This ensures that when activities list files are reprocessed, they don't
        overwrite the ts_data_available flag that was set during FIT file processing.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        """

        # Arrange.
        activity_data = {
            "activityId": 987654321,
            "activityName": "Morning Run",
            "activityType": {"typeId": 1, "typeKey": "running"},
            "eventType": {"typeId": 1, "typeKey": "other"},
            "startTimeGMT": "2022-01-01T07:00:00",
            "startTimeLocal": "2022-01-01T00:00:00",
            "endTimeGMT": "2022-01-01T08:30:00",
            "deviceId": 123456789,
            "manufacturer": "GARMIN",
            "timeZoneId": 1,
            "parent": False,
            "purposeful": True,
            "favorite": False,
            "pr": False,
            "hasPolyline": True,
            "hasImages": False,
            "hasVideo": False,
            "hasSplits": True,
            "hasHeatMap": False,
            "elevationCorrected": True,
            "atpActivity": False,
            "manualActivity": False,
            "autoCalcCalories": True,
        }

        mock_activity_with_id = Activity()
        mock_activity_with_id.activity_id = 987654321
        mock_upsert.return_value = [mock_activity_with_id]

        # Act.
        processor.user_id = 1
        processor._process_activity_base(activity_data, mock_session)

        # Assert.
        mock_upsert.assert_called_once()
        call_args = mock_upsert.call_args

        # Verify that update_columns parameter is provided and excludes ts_data_available.
        update_columns = call_args[1]["update_columns"]
        assert update_columns is not None
        assert "ts_data_available" not in update_columns
        assert "activity_id" not in update_columns  # Conflict column.

        # Verify other expected columns are included.
        assert "activity_name" in update_columns
        assert "device_id" in update_columns

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_activity_base_handles_missing_end_time_gmt(
        self, mock_upsert, processor, mock_session
    ):
        """
        Test that _process_activity_base handles missing endTimeGMT by calculating from
        duration. This ensures that historical activity data files without endTimeGMT
        field are processed correctly.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        """
        # Arrange - Historical activity data without endTimeGMT but with duration.
        activity_data = {
            "activityId": 123456789,
            "activityName": "Historical Run",
            "activityType": {"typeId": 1, "typeKey": "running"},
            "eventType": {"typeId": 1, "typeKey": "other"},
            "startTimeGMT": "2016-01-01T07:00:00",
            "startTimeLocal": "2016-01-01T00:00:00",
            # Note: endTimeGMT is missing - this is the key test condition.
            "duration": 3600,  # 1 hour in seconds.
            "deviceId": 123456789,
            "manufacturer": "GARMIN",
            "timeZoneId": 1,
            "parent": False,
            "purposeful": True,
            "favorite": False,
            "pr": False,
            "hasPolyline": True,
            "hasImages": False,
            "hasVideo": False,
            "hasSplits": True,
            "hasHeatMap": False,
            "elevationCorrected": True,
            "atpActivity": False,
            "manualActivity": False,
            "autoCalcCalories": True,
        }

        # Mock the return value with an Activity instance containing activity_id.
        mock_activity_with_id = Activity()
        mock_activity_with_id.activity_id = 123456789
        mock_upsert.return_value = [mock_activity_with_id]

        # Act.
        processor.user_id = 1
        result = processor._process_activity_base(activity_data, mock_session)

        # Assert.
        mock_upsert.assert_called_once()
        call_args = mock_upsert.call_args

        # Verify the Activity object was created with calculated end_ts.
        model_instances = call_args[1]["model_instances"]
        assert len(model_instances) == 1
        activity_instance = model_instances[0]

        # Verify start and end timestamps are correct.
        start_ts = activity_instance.start_ts
        end_ts = activity_instance.end_ts

        # Start time should be 2016-01-01T07:00:00 UTC.
        assert start_ts.year == 2016
        assert start_ts.month == 1
        assert start_ts.day == 1
        assert start_ts.hour == 7
        assert start_ts.minute == 0

        # End time should be start time + 1 hour (3600 seconds).
        assert end_ts.year == 2016
        assert end_ts.month == 1
        assert end_ts.day == 1
        assert end_ts.hour == 8
        assert end_ts.minute == 0

        # Verify duration is preserved in the activity record.
        assert activity_instance.duration == 3600

        # Verify the activity_id is correct.
        assert activity_instance.activity_id == 123456789

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_activity_base_handles_missing_device_fields(
        self, mock_upsert, processor, mock_session
    ):
        """
        Test that _process_activity_base handles missing device-related fields. This
        ensures that historical activity data files without deviceId, manufacturer, and
        timeZoneId fields are processed correctly with NULL values.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        """
        # Arrange - Historical activity data without device fields.
        activity_data = {
            "activityId": 987654321,
            "activityName": "Very Old Run",
            "activityType": {"typeId": 1, "typeKey": "running"},
            "eventType": {"typeId": 1, "typeKey": "other"},
            "startTimeGMT": "2015-01-01T07:00:00",
            "startTimeLocal": "2015-01-01T00:00:00",
            "endTimeGMT": "2015-01-01T08:00:00",
            # Note: deviceId, manufacturer, and timeZoneId are missing.
            "parent": False,
            "purposeful": True,
            "favorite": False,
            "pr": False,
            "hasPolyline": True,
            "hasImages": False,
            "hasVideo": False,
            "hasSplits": True,
            "hasHeatMap": False,
            "elevationCorrected": True,
            "atpActivity": False,
            "manualActivity": False,
            "autoCalcCalories": True,
        }

        # Mock the return value with an Activity instance containing activity_id.
        mock_activity_with_id = Activity()
        mock_activity_with_id.activity_id = 987654321
        mock_upsert.return_value = [mock_activity_with_id]

        # Act.
        processor.user_id = 1
        result = processor._process_activity_base(activity_data, mock_session)

        # Assert.
        mock_upsert.assert_called_once()
        call_args = mock_upsert.call_args

        # Verify the Activity object was created with NULL device fields.
        model_instances = call_args[1]["model_instances"]
        assert len(model_instances) == 1
        activity_instance = model_instances[0]

        # Verify device fields are None.
        assert activity_instance.device_id is None
        assert activity_instance.manufacturer is None
        assert activity_instance.time_zone_id is None

        # Verify other fields are still processed correctly.
        assert activity_instance.activity_id == 987654321
        assert activity_instance.activity_name == "Very Old Run"

        # Verify start and end timestamps are correct.
        start_ts = activity_instance.start_ts
        end_ts = activity_instance.end_ts

        assert start_ts.year == 2015
        assert start_ts.month == 1
        assert start_ts.day == 1
        assert start_ts.hour == 7
        assert start_ts.minute == 0

        assert end_ts.year == 2015
        assert end_ts.month == 1
        assert end_ts.day == 1
        assert end_ts.hour == 8
        assert end_ts.minute == 0

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_activity_base_handles_missing_boolean_fields(
        self, mock_upsert, processor, mock_session
    ):
        """
        Test that _process_activity_base handles missing boolean fields from 2016 data.
        This ensures that historical activity data files without hasSplits,
        elevationCorrected, and atpActivity fields are processed correctly with NULL
        values.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        """
        # Arrange - 2016 activity data without hasSplits, elevationCorrected, atpActivity.
        activity_data = {
            "activityId": 1021028774,
            "activityName": "New York City Running",
            "activityType": {"typeId": 1, "typeKey": "running"},
            "eventType": {"typeId": 9, "typeKey": "uncategorized"},
            "startTimeGMT": "2016-01-16 17:32:31",
            "startTimeLocal": "2016-01-16 12:32:31",
            "duration": 2077.619,
            "distance": 7360.03,
            "timeZoneId": 149,
            "parent": False,
            "purposeful": False,
            "favorite": False,
            "pr": False,
            "hasPolyline": True,
            "hasImages": False,
            "hasVideo": False,
            "hasHeatMap": False,
            "manualActivity": False,
            "autoCalcCalories": False,
            # Note: hasSplits, elevationCorrected, atpActivity are missing.
        }

        # Mock the return value with an Activity instance containing activity_id.
        mock_activity_with_id = Activity()
        mock_activity_with_id.activity_id = 1021028774
        mock_upsert.return_value = [mock_activity_with_id]

        # Act.
        processor.user_id = 1
        result = processor._process_activity_base(activity_data, mock_session)

        # Assert.
        mock_upsert.assert_called_once()
        call_args = mock_upsert.call_args

        # Verify the Activity object was created with NULL boolean fields.
        model_instances = call_args[1]["model_instances"]
        assert len(model_instances) == 1
        activity_instance = model_instances[0]

        # Verify missing boolean fields are None.
        assert activity_instance.has_splits is None
        assert activity_instance.elevation_corrected is None
        assert activity_instance.atp_activity is None

        # Verify present boolean fields are processed correctly.
        assert activity_instance.has_polyline is True
        assert activity_instance.has_images is False
        assert activity_instance.has_video is False
        assert activity_instance.has_heat_map is False
        assert activity_instance.parent is False
        assert activity_instance.purposeful is False
        assert activity_instance.favorite is False
        assert activity_instance.pr is False
        assert activity_instance.manual_activity is False
        assert activity_instance.auto_calc_calories is False

        # Verify other fields are still processed correctly.
        assert activity_instance.activity_id == 1021028774
        assert activity_instance.activity_name == "New York City Running"
        assert activity_instance.duration == 2077.619
        assert activity_instance.distance == 7360.03

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_activity_base_handles_missing_activity_name(
        self, mock_upsert, processor, mock_session
    ):
        """
        Test that _process_activity_base handles missing activityName field. This
        ensures that very old activity data files without activityName are processed
        correctly with NULL value.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        """
        # Arrange - Very old activity data without activityName.
        activity_data = {
            "activityId": 999999999,
            # Note: activityName is missing - this is the key test condition.
            "activityType": {"typeId": 1, "typeKey": "running"},
            "eventType": {"typeId": 9, "typeKey": "uncategorized"},
            "startTimeGMT": "2014-01-01T10:00:00",
            "startTimeLocal": "2014-01-01T05:00:00",
            "endTimeGMT": "2014-01-01T11:00:00",
            "duration": 3600,
            "parent": False,
            "purposeful": False,
            "favorite": False,
            "pr": False,
            "hasPolyline": True,
            "hasImages": False,
            "hasVideo": False,
            "hasHeatMap": False,
            "manualActivity": False,
            "autoCalcCalories": False,
        }

        # Mock the return value with an Activity instance containing activity_id.
        mock_activity_with_id = Activity()
        mock_activity_with_id.activity_id = 999999999
        mock_upsert.return_value = [mock_activity_with_id]

        # Act.
        processor.user_id = 1
        result = processor._process_activity_base(activity_data, mock_session)

        # Assert.
        mock_upsert.assert_called_once()
        call_args = mock_upsert.call_args

        # Verify the Activity object was created with NULL activity_name.
        model_instances = call_args[1]["model_instances"]
        assert len(model_instances) == 1
        activity_instance = model_instances[0]

        # Verify activity_name is None.
        assert activity_instance.activity_name is None

        # Verify other fields are still processed correctly.
        assert activity_instance.activity_id == 999999999
        assert activity_instance.duration == 3600

        # Verify boolean fields are processed correctly.
        assert activity_instance.parent is False
        assert activity_instance.purposeful is False
        assert activity_instance.favorite is False
        assert activity_instance.pr is False

    def test_process_file_set(
        self, processor, mock_session, temp_dir, sample_sleep_data
    ):
        """
        Test process_file_set method.

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        :param sample_sleep_data: Sample sleep data fixture.
        """

        # Arrange.
        sleep_file = temp_dir / "123456789_SLEEP_2022-01-01T00-00-00Z.json"
        with open(sleep_file, "w", encoding="utf-8") as f:
            json.dump(sample_sleep_data, f)

        # Create FileSet with files dict - using enum object as key.
        file_set = FileSet(files={GARMIN_FILE_TYPES.SLEEP: [sleep_file]})

        # Mock user existence check.
        mock_session.query.return_value.filter.return_value.first.return_value = None

        # Act.
        with patch.object(
            processor, "_process_sleep"
        ) as mock_process_sleep, patch.object(
            processor, "_ensure_user_exists", return_value=1
        ) as mock_ensure_user:
            processor.process_file_set(file_set, mock_session)

        # Assert.
        mock_process_sleep.assert_called_once_with(sleep_file, mock_session)
        mock_ensure_user.assert_called_once_with("123456789", mock_session)

    # Steps Processing Tests.
    @pytest.fixture
    def sample_steps_data(self) -> List[Dict]:
        """
        Create sample steps data based on provided JSON structure.

        :return: Sample steps data list.
        """

        return [
            {
                "startGMT": "2025-08-07T07:00:00.0",
                "endGMT": "2025-08-07T07:15:00.0",
                "steps": 0,
                "pushes": 0,
                "primaryActivityLevel": "sleeping",
                "activityLevelConstant": True,
            },
            {
                "startGMT": "2025-08-07T07:15:00.0",
                "endGMT": "2025-08-07T07:30:00.0",
                "steps": 27,
                "pushes": 0,
                "primaryActivityLevel": "sleeping",
                "activityLevelConstant": True,
            },
            {
                "startGMT": "2025-08-07T14:15:00.0",
                "endGMT": "2025-08-07T14:30:00.0",
                "steps": 2206,
                "pushes": 0,
                "primaryActivityLevel": "highlyActive",
                "activityLevelConstant": True,
            },
            {
                "startGMT": "2025-08-07T15:00:00.0",
                "endGMT": "2025-08-07T15:15:00.0",
                "steps": 1307,
                "pushes": 0,
                "primaryActivityLevel": "active",
                "activityLevelConstant": False,
            },
        ]

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_steps_file(
        self, mock_upsert, processor, mock_session, temp_dir, sample_steps_data
    ):
        """
        Test _process_steps with complete data.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        :param sample_steps_data: Sample steps data fixture.
        """

        # Arrange.
        steps_file = temp_dir / "15007510_STEPS_2025-08-07T12:00:00Z.json"
        with open(steps_file, "w", encoding="utf-8") as f:
            json.dump(sample_steps_data, f)
        # Act.
        processor.user_id = 1
        processor._process_steps(steps_file, mock_session)
        # Assert.
        mock_upsert.assert_called_once()
        _, kwargs = mock_upsert.call_args
        model_instances = kwargs["model_instances"]
        assert len(model_instances) == 4  # 4 step measurements
        assert all(isinstance(m, Steps) for m in model_instances)
        assert kwargs["conflict_columns"] == ["user_id", "timestamp"]
        assert kwargs["on_conflict_update"] is False
        # Check first steps record.
        first_record = model_instances[0]
        assert first_record.user_id == 1
        assert first_record.value == 0
        assert first_record.activity_level == "sleeping"
        assert first_record.activity_level_constant is True
        # Check highly active record.
        active_record = model_instances[2]
        assert active_record.value == 2206
        assert active_record.activity_level == "highlyActive"
        assert active_record.activity_level_constant is True

    def test_process_steps_missing_data(self, processor, mock_session, temp_dir):
        """
        Test _process_steps with empty data array.

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        empty_data = []
        steps_file = temp_dir / "15007510_STEPS_2025-08-07T12:00:00Z.json"
        with open(steps_file, "w", encoding="utf-8") as f:
            json.dump(empty_data, f)
        # Act.
        with patch(
            "dags.pipelines.garmin.process.upsert_model_instances"
        ) as mock_upsert:
            processor.user_id = 1
            processor._process_steps(steps_file, mock_session)
        # Assert.
        mock_upsert.assert_not_called()  # No records should be processed

    def test_process_steps_invalid_values(
        self, processor, mock_session, temp_dir, sample_steps_data
    ):
        """
        Test _process_steps filters out invalid values (None endGMT, None steps).

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        :param sample_steps_data: Sample steps data fixture.
        """

        # Arrange - add invalid values to the data.
        modified_data = copy.deepcopy(sample_steps_data)
        modified_data.extend(
            [
                {
                    "startGMT": "2025-08-07T16:00:00.0",
                    "endGMT": None,  # Invalid endGMT
                    "steps": 100,
                    "primaryActivityLevel": "active",
                    "activityLevelConstant": False,
                },
                {
                    "startGMT": "2025-08-07T16:15:00.0",
                    "endGMT": "2025-08-07T16:30:00.0",
                    "steps": None,  # Invalid steps
                    "primaryActivityLevel": "sedentary",
                    "activityLevelConstant": True,
                },
            ]
        )
        steps_file = temp_dir / "15007510_STEPS_2025-08-07T12:00:00Z.json"
        with open(steps_file, "w", encoding="utf-8") as f:
            json.dump(modified_data, f)
        # Act.
        with patch(
            "dags.pipelines.garmin.process.upsert_model_instances"
        ) as mock_upsert:
            processor.user_id = 1
            processor._process_steps(steps_file, mock_session)
        # Assert.
        mock_upsert.assert_called_once()
        _, kwargs = mock_upsert.call_args
        model_instances = kwargs["model_instances"]
        assert len(model_instances) == 4  # Only valid records processed

    def test_process_steps_file_routing(self, processor, mock_session, temp_dir):
        """
        Test that STEPS files are properly routed to processing method.

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        steps_file = temp_dir / "123456789_STEPS_2022-01-01T00:00:00Z.json"
        steps_file.write_text(
            '[{"endGMT": "2022-01-01T00:15:00.0", "steps": 50, '
            '"primaryActivityLevel": "active", "activityLevelConstant": false}]'
        )
        # Create FileSet with STEPS files.
        file_set = FileSet(files={GARMIN_FILE_TYPES.STEPS: [steps_file]})
        # Mock user existence check.
        mock_session.query.return_value.filter.return_value.first.return_value = None
        # Act.
        with patch.object(
            processor, "_process_steps"
        ) as mock_process_steps, patch.object(
            processor, "_ensure_user_exists", return_value=1
        ) as mock_ensure_user:
            processor.process_file_set(file_set, mock_session)
        # Assert.
        mock_process_steps.assert_called_once_with(steps_file, mock_session)
        mock_ensure_user.assert_called_once_with("123456789", mock_session)

    def test_process_sleep_file_missing_data(self, processor, mock_session, temp_dir):
        """
        Test _process_sleep with missing dailySleepDTO.

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        invalid_data = {"otherData": "value"}
        sleep_file = temp_dir / "123456789_SLEEP_2022-01-01T00-00-00Z.json"
        with open(sleep_file, "w", encoding="utf-8") as f:
            json.dump(invalid_data, f)

        # Act.
        # Should complete without error but not process any data.
        processor.user_id = 1
        processor._process_sleep(sleep_file, mock_session)

        # Assert - no data should be processed, but no error should occur.

    # Training Status Processing Tests.
    @pytest.fixture
    def sample_training_status_data(self) -> Dict:
        """
        Create sample training status data based on provided JSON structure.

        :return: Sample training status data dictionary.
        """

        return {
            "userId": 15007510,
            "mostRecentVO2Max": {
                "userId": 15007510,
                "generic": {
                    "calendarDate": "2025-08-09",
                    "vo2MaxPreciseValue": 58.9,
                    "vo2MaxValue": 59.0,
                    "fitnessAge": None,
                    "fitnessAgeDescription": None,
                    "maxMetCategory": 0,
                },
                "cycling": {
                    "calendarDate": "2025-08-15",
                    "vo2MaxPreciseValue": 58.5,
                    "vo2MaxValue": 59.0,
                    "fitnessAge": None,
                    "fitnessAgeDescription": None,
                    "maxMetCategory": 1,
                },
                "heatAltitudeAcclimation": {
                    "calendarDate": "2025-08-15",
                    "altitudeAcclimationDate": "2025-08-16",
                    "previousAltitudeAcclimationDate": "2025-08-16",
                    "heatAcclimationDate": "2025-08-16",
                    "previousHeatAcclimationDate": "2025-08-14",
                    "altitudeAcclimation": 0,
                    "previousAltitudeAcclimation": 0,
                    "heatAcclimationPercentage": 23,
                    "previousHeatAcclimationPercentage": 25,
                    "heatTrend": "DEACCLIMATIZING",
                    "altitudeTrend": None,
                    "currentAltitude": 8,
                    "previousAltitude": 0,
                    "acclimationPercentage": 0,
                    "previousAcclimationPercentage": 0,
                    "altitudeAcclimationLocalTimestamp": "2025-08-15T23:56:26.0",
                },
            },
            "mostRecentTrainingLoadBalance": {
                "userId": 15007510,
                "metricsTrainingLoadBalanceDTOMap": {
                    "3474921807": {
                        "calendarDate": "2025-08-15",
                        "deviceId": 3474921807,
                        "monthlyLoadAerobicLow": 1540.738,
                        "monthlyLoadAerobicHigh": 1366.2461,
                        "monthlyLoadAnaerobic": 492.51825,
                        "monthlyLoadAerobicLowTargetMin": 544,
                        "monthlyLoadAerobicLowTargetMax": 1196,
                        "monthlyLoadAerobicHighTargetMin": 652,
                        "monthlyLoadAerobicHighTargetMax": 1305,
                        "monthlyLoadAnaerobicTargetMin": 217,
                        "monthlyLoadAnaerobicTargetMax": 652,
                        "trainingBalanceFeedbackPhrase": "ABOVE_TARGETS",
                        "primaryTrainingDevice": True,
                    }
                },
            },
            "mostRecentTrainingStatus": {
                "userId": 15007510,
                "latestTrainingStatusData": {
                    "3474921807": {
                        "calendarDate": "2025-08-15",
                        "sinceDate": "2025-08-10",
                        "weeklyTrainingLoad": None,
                        "trainingStatus": 8,
                        "timestamp": 1755306440000,
                        "deviceId": 3474921807,
                        "loadTunnelMin": None,
                        "loadTunnelMax": None,
                        "loadLevelTrend": None,
                        "sport": "RUNNING",
                        "subSport": "GENERIC",
                        "fitnessTrendSport": "RUNNING",
                        "fitnessTrend": 1,
                        "trainingStatusFeedbackPhrase": "STRAINED_1",
                        "trainingPaused": False,
                        "acuteTrainingLoadDTO": {
                            "acwrPercent": 38,
                            "acwrStatus": "OPTIMAL",
                            "acwrStatusFeedback": "FEEDBACK_2",
                            "dailyTrainingLoadAcute": 811,
                            "maxTrainingLoadChronic": 1261.5,
                            "minTrainingLoadChronic": 672.8000000000001,
                            "dailyTrainingLoadChronic": 841,
                            "dailyAcuteChronicWorkloadRatio": 0.9,
                        },
                        "primaryTrainingDevice": True,
                    }
                },
            },
        }

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_training_status_file(
        self,
        mock_upsert,
        processor,
        mock_session,
        temp_dir,
        sample_training_status_data,
    ):
        """
        Test _process_training_status with complete data.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        :param sample_training_status_data: Sample training status data fixture.
        """

        # Arrange.
        training_status_file = (
            temp_dir / "15007510_TRAINING_STATUS_2025-08-15T12-00-00Z.json"
        )
        with open(training_status_file, "w", encoding="utf-8") as f:
            json.dump(sample_training_status_data, f)

        # Act.
        processor.user_id = 1
        processor._process_training_status(training_status_file, mock_session)

        # Assert.
        # VO2Max, Acclimation, and TrainingLoad records are now processed via separate
        # upsert_model_instances calls.
        assert (
            mock_upsert.call_count == 5
        )  # VO2 max (2 calls) + Acclimation (1 call) + TrainingLoad records (2 calls).
        assert mock_session.merge.call_count == 0  # No more session.merge calls.

        # Check upsert calls - first two should be VO2Max, last two should be
        # TrainingLoad.
        upsert_calls = mock_upsert.call_args_list

        # First upsert call should be VO2Max generic record.
        generic_vo2_call = upsert_calls[0]
        generic_vo2_instances = generic_vo2_call[1]["model_instances"]
        assert len(generic_vo2_instances) == 1  # Generic record only.
        assert isinstance(generic_vo2_instances[0], VO2Max)
        assert generic_vo2_call[1]["update_columns"] == ["vo2_max_generic"]

        # Second upsert call should be VO2Max cycling record.
        cycling_vo2_call = upsert_calls[1]
        cycling_vo2_instances = cycling_vo2_call[1]["model_instances"]
        assert len(cycling_vo2_instances) == 1  # Cycling record only.
        assert isinstance(cycling_vo2_instances[0], VO2Max)
        assert cycling_vo2_call[1]["update_columns"] == ["vo2_max_cycling"]

        # Third upsert call should be Acclimation record.
        acclimation_call = upsert_calls[2]
        acclimation_instances = acclimation_call[1]["model_instances"]
        assert len(acclimation_instances) == 1  # Acclimation record only.
        assert isinstance(acclimation_instances[0], Acclimation)

        # Fourth upsert call should be TrainingLoad balance record.
        balance_call = upsert_calls[3]
        balance_instances = balance_call[1]["model_instances"]
        assert len(balance_instances) == 1  # Balance record only.
        assert isinstance(balance_instances[0], TrainingLoad)

        # Fifth upsert call should be TrainingLoad status record (merged with
        # balance due to same date).
        status_call = upsert_calls[4]
        status_instances = status_call[1]["model_instances"]
        assert len(status_instances) == 1  # Status record (merged with balance).
        assert isinstance(status_instances[0], TrainingLoad)

        # No more session.merge calls since all processing now uses
        # upsert_model_instances
        assert mock_session.merge.call_count == 0

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_vo2_max_and_acclimation_data(
        self, mock_upsert, processor, mock_session, sample_training_status_data
    ):
        """
        Test _process_vo2_max_and_acclimation extracts correct VO2 max and acclimation
        values.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param sample_training_status_data: Sample training status data fixture.
        """

        # Act.
        processor.user_id = 1
        processor._process_vo2_max_and_acclimation(
            sample_training_status_data, mock_session
        )

        # Assert.
        # VO2Max and Acclimation records are now processed via separate
        # upsert_model_instances calls.
        assert (
            mock_upsert.call_count == 3
        )  # VO2 max records (generic and cycling separately) + Acclimation (1 call).
        assert mock_session.merge.call_count == 0  # No more session.merge calls.

        # Check VO2 max records from upsert calls.
        upsert_calls = mock_upsert.call_args_list

        # First call should be generic VO2Max.
        generic_call = upsert_calls[0]
        generic_instances = generic_call[1]["model_instances"]
        assert len(generic_instances) == 1
        assert generic_call[1]["conflict_columns"] == ["user_id", "date"]
        assert generic_call[1]["update_columns"] == ["vo2_max_generic"]
        assert generic_call[1]["on_conflict_update"] is True

        generic_record = generic_instances[0]
        assert generic_record.user_id == 1
        assert generic_record.date == "2025-08-09"
        assert generic_record.vo2_max_generic == 58.9

        # Second call should be cycling VO2Max.
        cycling_call = upsert_calls[1]
        cycling_instances = cycling_call[1]["model_instances"]
        assert len(cycling_instances) == 1
        assert cycling_call[1]["conflict_columns"] == ["user_id", "date"]
        assert cycling_call[1]["update_columns"] == ["vo2_max_cycling"]
        assert cycling_call[1]["on_conflict_update"] is True

        cycling_record = cycling_instances[0]
        assert cycling_record.user_id == 1
        assert cycling_record.date == "2025-08-15"
        assert cycling_record.vo2_max_cycling == 58.5

        # Third call should be Acclimation.
        acclimation_call = upsert_calls[2]
        acclimation_instances = acclimation_call[1]["model_instances"]
        assert len(acclimation_instances) == 1
        assert acclimation_call[1]["conflict_columns"] == ["user_id", "date"]
        assert acclimation_call[1]["on_conflict_update"] is True

        acclimation_record = acclimation_instances[0]
        assert acclimation_record.user_id == 1
        assert acclimation_record.date == "2025-08-15"
        assert acclimation_record.heat_acclimation_percentage == 23
        assert acclimation_record.heat_trend == "DEACCLIMATIZING"
        assert acclimation_record.altitude_acclimation == 0
        assert acclimation_record.current_altitude == 8
        assert acclimation_record.acclimation_percentage == 0
        assert acclimation_record.altitude_trend is None

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_training_load_data(
        self, mock_upsert, processor, mock_session, sample_training_status_data
    ):
        """
        Test _process_training_load merges balance and status data with same date.

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param sample_training_status_data: Sample training status data fixture.
        """

        # Act.
        processor.user_id = 1
        processor._process_training_load(sample_training_status_data, mock_session)

        # Assert.
        # Should call upsert twice: once for balance, once for merged status data.
        assert mock_upsert.call_count == 2
        assert mock_session.merge.call_count == 0  # No immediate merge calls.

        upsert_calls = mock_upsert.call_args_list

        # First call: balance data only.
        balance_call = upsert_calls[0]
        assert balance_call[1]["session"] == mock_session
        assert balance_call[1]["conflict_columns"] == ["user_id", "date"]
        assert balance_call[1]["on_conflict_update"] is True
        assert len(balance_call[1]["model_instances"]) == 1
        assert "update_columns" in balance_call[1]

        balance_record = balance_call[1]["model_instances"][0]
        assert isinstance(balance_record, TrainingLoad)
        assert balance_record.user_id == 1
        assert balance_record.date == "2025-08-15"

        # Check training load balance fields.
        assert balance_record.monthly_load_aerobic_low == 1540.738
        assert balance_record.monthly_load_aerobic_high == 1366.2461
        assert balance_record.monthly_load_anaerobic == 492.51825
        assert balance_record.training_balance_feedback_phrase == "ABOVE_TARGETS"

        # Second call: merged record with status data (same date).
        status_call = upsert_calls[1]
        assert status_call[1]["session"] == mock_session
        assert status_call[1]["conflict_columns"] == ["user_id", "date"]
        assert status_call[1]["on_conflict_update"] is True
        assert len(status_call[1]["model_instances"]) == 1
        assert "update_columns" in status_call[1]

        status_record = status_call[1]["model_instances"][0]
        assert isinstance(status_record, TrainingLoad)
        assert status_record.user_id == 1
        assert status_record.date == "2025-08-15"

        # Check that status data is on the same record (merged because same date).
        # Check ACWR fields.
        assert status_record.acwr_percent == 38
        assert status_record.acwr_status == "OPTIMAL"
        assert status_record.acwr_status_feedback == "FEEDBACK_2"
        assert status_record.daily_training_load_acute == 811
        assert status_record.daily_training_load_chronic == 841
        assert status_record.daily_acute_chronic_workload_ratio == 0.9

        # Check training status fields.
        assert status_record.training_status == 8
        assert status_record.training_status_feedback_phrase == "STRAINED_1"

        # The merged record should also have the balance fields.
        assert status_record.monthly_load_aerobic_low == 1540.738
        assert status_record.monthly_load_aerobic_high == 1366.2461

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_training_load_data_different_dates(
        self, mock_upsert, processor, mock_session, sample_training_status_data
    ):
        """
        Test _process_training_load with different dates creates separate records.

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param sample_training_status_data: Sample training status data fixture.
        """

        # Arrange - modify data to have different dates.
        modified_data = copy.deepcopy(sample_training_status_data)
        modified_data["mostRecentTrainingStatus"]["latestTrainingStatusData"][
            "3474921807"
        ]["calendarDate"] = "2025-08-16"

        # Act.
        processor.user_id = 1
        processor._process_training_load(modified_data, mock_session)

        # Assert.
        # Should call upsert twice: separate calls for different dates.
        assert mock_upsert.call_count == 2
        assert mock_session.merge.call_count == 0  # No immediate merge calls.

        upsert_calls = mock_upsert.call_args_list

        # First call: balance record (2025-08-15).
        balance_call = upsert_calls[0]
        balance_record = balance_call[1]["model_instances"][0]
        assert balance_record.date == "2025-08-15"
        assert balance_record.monthly_load_aerobic_low == 1540.738

        # Second call: status record (2025-08-16 - different date).
        status_call = upsert_calls[1]
        status_record = status_call[1]["model_instances"][0]
        assert status_record.date == "2025-08-16"
        assert status_record.training_status == 8

        # Status record should NOT have balance data (different date).
        assert status_record.monthly_load_aerobic_low is None

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_training_load_data_missing_sections(
        self, mock_upsert, processor, mock_session
    ):
        """
        Test _process_training_load with missing sections handles gracefully.

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        """

        # Arrange.
        empty_data = {}

        # Act.
        processor.user_id = 1
        processor._process_training_load(empty_data, mock_session)

        # Assert.
        mock_upsert.assert_not_called()  # No upsert calls with empty data.
        assert mock_session.merge.call_count == 0  # No merge calls.

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_training_load_data_unexpected_data_types(
        self, mock_upsert, processor, mock_session, sample_training_status_data
    ):
        """
        Test _process_training_load handles unexpected data types gracefully.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param sample_training_status_data: Sample training status data fixture.
        """

        # Arrange - add unexpected data types to balance data.
        modified_data = copy.deepcopy(sample_training_status_data)
        balance_data = modified_data["mostRecentTrainingLoadBalance"][
            "metricsTrainingLoadBalanceDTOMap"
        ]["3474921807"]

        # Add fields with unexpected data types.
        balance_data["monthlyLoadAerobicLow"] = [1540.738]  # List instead of float.
        balance_data["monthlyLoadAerobicHigh"] = {
            "value": 1366.2461
        }  # Dict instead of float.
        balance_data["monthlyLoadAnaerobic"] = object()  # Object instead of number.

        # Act.
        processor.user_id = 1
        processor._process_training_load(modified_data, mock_session)

        # Assert.
        # Should still create training load records with the unexpected values as-is.
        assert mock_upsert.call_count == 2  # Balance and status records.
        call_args = mock_upsert.call_args
        training_load_records = call_args[1]["model_instances"]

        # Find the balance record.
        balance_record = next(
            (
                r
                for r in training_load_records
                if r.training_balance_feedback_phrase is not None
            ),
            None,
        )
        assert balance_record is not None

        # The unexpected data types should be set as-is on the model
        # (SQLAlchemy will handle type conversion if possible)
        assert balance_record.monthly_load_aerobic_low == [1540.738]
        assert balance_record.monthly_load_aerobic_high == {"value": 1366.2461}

    def test_process_training_status_file_routing(
        self, processor, mock_session, temp_dir
    ):
        """
        Test that TRAINING_STATUS files are properly routed to processing method.

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        training_status_file = (
            temp_dir / "123456789_TRAINING_STATUS_2022-01-01T00-00-00Z.json"
        )
        training_status_file.write_text('{"mostRecentVO2Max": {}}')

        # Create FileSet with TRAINING_STATUS files.
        file_set = FileSet(
            files={GARMIN_FILE_TYPES.TRAINING_STATUS: [training_status_file]}
        )

        # Mock user existence check.
        mock_session.query.return_value.filter.return_value.first.return_value = None

        # Act.
        with patch.object(
            processor, "_process_training_status"
        ) as mock_process_training_status, patch.object(
            processor, "_ensure_user_exists", return_value=1
        ) as mock_ensure_user:
            processor.process_file_set(file_set, mock_session)

        # Assert.
        mock_process_training_status.assert_called_once_with(
            training_status_file, mock_session
        )
        mock_ensure_user.assert_called_once_with("123456789", mock_session)

    @pytest.fixture
    def sample_training_readiness_data(self) -> List[Dict]:
        """
        Create sample training readiness data based on provided JSON structure.

        :return: Sample training readiness data list.
        """

        return [
            {
                "userProfilePK": 15007510,
                "calendarDate": "2025-08-07",
                "timestamp": "2025-08-07T18:56:58.0",
                "timestampLocal": "2025-08-07T11:56:58.0",
                "deviceId": 3474921807,
                "level": "MODERATE",
                "feedbackLong": "MOD_RT_MOD_SS_MOD",
                "feedbackShort": "LISTEN_TO_YOUR_BODY",
                "score": 50,
                "sleepScore": 77,
                "sleepScoreFactorPercent": 65,
                "sleepScoreFactorFeedback": "MODERATE",
                "recoveryTime": 1524,
                "recoveryTimeFactorPercent": 59,
                "recoveryTimeFactorFeedback": "MODERATE",
                "acwrFactorPercent": 95,
                "acwrFactorFeedback": "GOOD",
                "acuteLoad": 730,
                "stressHistoryFactorPercent": 77,
                "stressHistoryFactorFeedback": "GOOD",
                "hrvFactorPercent": 88,
                "hrvFactorFeedback": "GOOD",
                "hrvWeeklyAverage": 75,
                "sleepHistoryFactorPercent": 69,
                "sleepHistoryFactorFeedback": "MODERATE",
                "validSleep": True,
                "inputContext": "UPDATE_REALTIME_VARIABLES",
                "primaryActivityTracker": True,
                "recoveryTimeChangePhrase": None,
                "sleepHistoryFactorFeedbackPhrase": None,
                "hrvFactorFeedbackPhrase": None,
                "stressHistoryFactorFeedbackPhrase": None,
                "acwrFactorFeedbackPhrase": None,
                "recoveryTimeFactorFeedbackPhrase": None,
                "sleepScoreFactorFeedbackPhrase": None,
            },
            {
                "userProfilePK": 15007510,
                "calendarDate": "2025-08-07",
                "timestamp": "2025-08-07T15:07:53.0",
                "timestampLocal": "2025-08-07T08:07:53.0",
                "deviceId": 3474921807,
                "level": "LOW",
                "feedbackLong": "LOW_RT_MOD_OR_LOW_SS_MOD",
                "feedbackShort": "FOCUS_ON_ENERGY_LEVELS",
                "score": 47,
                "sleepScore": 77,
                "sleepScoreFactorPercent": 65,
                "sleepScoreFactorFeedback": "MODERATE",
                "recoveryTime": 1752,
                "recoveryTimeFactorPercent": 52,
                "recoveryTimeFactorFeedback": "MODERATE",
                "acwrFactorPercent": 95,
                "acwrFactorFeedback": "GOOD",
                "acuteLoad": 730,
                "stressHistoryFactorPercent": 77,
                "stressHistoryFactorFeedback": "GOOD",
                "hrvFactorPercent": 88,
                "hrvFactorFeedback": "GOOD",
                "hrvWeeklyAverage": 75,
                "sleepHistoryFactorPercent": 69,
                "sleepHistoryFactorFeedback": "MODERATE",
                "validSleep": True,
                "inputContext": "AFTER_POST_EXERCISE_RESET",
                "primaryActivityTracker": True,
                "recoveryTimeChangePhrase": "REACHED_ZERO",
                "sleepHistoryFactorFeedbackPhrase": None,
                "hrvFactorFeedbackPhrase": None,
                "stressHistoryFactorFeedbackPhrase": None,
                "acwrFactorFeedbackPhrase": None,
                "recoveryTimeFactorFeedbackPhrase": None,
                "sleepScoreFactorFeedbackPhrase": None,
            },
        ]

    def test_process_training_readiness_file(
        self, processor, mock_session, temp_dir, sample_training_readiness_data
    ):
        """
        Test _process_training_readiness with complete data.

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        :param sample_training_readiness_data: Sample training readiness data fixture.
        """

        # Arrange.
        training_readiness_file = (
            temp_dir / "15007510_TRAINING_READINESS_2025-08-07T12:00:00Z.json"
        )
        with open(training_readiness_file, "w", encoding="utf-8") as f:
            json.dump(sample_training_readiness_data, f)

        # Mock upsert_model_instances.
        with patch(
            "dags.pipelines.garmin.process.upsert_model_instances"
        ) as mock_upsert:
            # Act.
            processor.user_id = 1
            processor._process_training_readiness(training_readiness_file, mock_session)

            # Assert.
            mock_upsert.assert_called_once()
            call_args = mock_upsert.call_args

            # Verify the model instances passed to upsert.
            model_instances = call_args[1]["model_instances"]
            assert len(model_instances) == 2  # Two records in sample data.

            # Verify all instances are TrainingReadiness models.
            for instance in model_instances:
                assert isinstance(instance, TrainingReadiness)

            # Verify conflict columns.
            assert call_args[1]["conflict_columns"] == ["user_id", "timestamp"]
            assert call_args[1]["on_conflict_update"] is True

    def test_process_training_readiness_field_extraction(
        self, processor, sample_training_readiness_data
    ):
        """
        Test that training readiness field extraction follows plan requirements.

        Verifies:
        - Excluded fields are not processed (userProfilePK, calendarDate,
          timestampLocal, deviceId).
        - Timezone offset calculation.
        - Snake case field conversion.

        :param processor: GarminProcessor fixture.
        :param sample_training_readiness_data: Sample training readiness data fixture.
        """

        # Arrange - use first record from sample data.
        single_record = copy.deepcopy(sample_training_readiness_data[0])

        # Use the actual file processing logic to test field extraction.
        readiness_data = single_record

        # Extract and exclude fields as per implementation.
        readiness_data.pop("userProfilePK", None)
        readiness_data.pop("calendarDate", None)
        timestamp_local_str = readiness_data.pop("timestampLocal", None)
        readiness_data.pop("deviceId", None)

        # Extract timestamp.
        timestamp_str = readiness_data.pop("timestamp", None)
        timestamp_utc = datetime.fromisoformat(timestamp_str)

        # Calculate timezone offset.
        if timestamp_local_str:
            timestamp_local = datetime.fromisoformat(timestamp_local_str)
            offset_seconds = (timestamp_local - timestamp_utc).total_seconds()
            timezone_offset_hours = offset_seconds / 3600
        else:
            timezone_offset_hours = 0.0

        # Build record.
        readiness_record = {
            "user_id": 123,
            "timestamp": timestamp_utc,
            "timezone_offset_hours": timezone_offset_hours,
        }

        # Process remaining fields with snake_case conversion.
        for field_name, field_value in readiness_data.items():
            snake_case_name = processor._convert_field_name(field_name)
            readiness_record[snake_case_name] = field_value

        # Assert timezone offset calculation.
        expected_offset = -7.0  # UTC-7 based on sample timestamps.
        assert readiness_record["timezone_offset_hours"] == expected_offset

        # Assert excluded fields are not present.
        assert "user_profile_pk" not in readiness_record
        assert "calendar_date" not in readiness_record
        assert "timestamp_local" not in readiness_record
        assert "device_id" not in readiness_record

        # Assert snake_case conversion for some key fields.
        assert "feedback_long" in readiness_record
        assert "sleep_score_factor_percent" in readiness_record
        assert "recovery_time_factor_feedback" in readiness_record
        assert "input_context" in readiness_record

        # Assert values are correct.
        assert readiness_record["level"] == "MODERATE"
        assert readiness_record["score"] == 50
        assert readiness_record["valid_sleep"] is True

        # Assert null values are included (not skipped).
        assert "recovery_time_change_phrase" in readiness_record
        assert readiness_record["recovery_time_change_phrase"] is None
        assert "sleep_history_factor_feedback_phrase" in readiness_record
        assert readiness_record["sleep_history_factor_feedback_phrase"] is None

    def test_process_training_readiness_empty_data(self, processor, mock_session):
        """
        Test _process_training_readiness with empty data.

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        """

        # Arrange.
        empty_data = []

        # Act.
        with patch(
            "dags.pipelines.garmin.process.upsert_model_instances"
        ) as mock_upsert:
            with patch.object(processor, "_load_json_file", return_value=empty_data):
                processor.user_id = 1
                processor._process_training_readiness(Path("dummy"), mock_session)

        # Assert.
        mock_upsert.assert_not_called()  # No records to process.

    def test_process_training_readiness_missing_timestamp(
        self, processor, mock_session
    ):
        """
        Test _process_training_readiness skips records with missing timestamp.

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        """

        # Arrange.
        incomplete_data = [
            {"level": "HIGH", "score": 85},  # Missing timestamp.
            {"timestamp": "2025-08-07T12:00:00.0", "level": "LOW", "score": 30},
        ]

        # Act.
        with patch(
            "dags.pipelines.garmin.process.upsert_model_instances"
        ) as mock_upsert:
            with patch.object(
                processor, "_load_json_file", return_value=incomplete_data
            ):
                processor.user_id = 1
                processor._process_training_readiness(Path("dummy"), mock_session)

                # Assert.
                mock_upsert.assert_called_once()
                model_instances = mock_upsert.call_args[1]["model_instances"]
                assert len(model_instances) == 1  # Only one valid record processed.

    def test_process_training_readiness_file_routing(
        self, processor, mock_session, temp_dir
    ):
        """
        Test that TRAINING_READINESS files are properly routed to processing method.

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        training_readiness_file = (
            temp_dir / "123456789_TRAINING_READINESS_2022-01-01T00-00-00Z.json"
        )
        training_readiness_file.write_text('[{"timestamp": "2025-01-01T12:00:00.0"}]')

        # Create FileSet with TRAINING_READINESS files.
        file_set = FileSet(
            files={GARMIN_FILE_TYPES.TRAINING_READINESS: [training_readiness_file]}
        )

        # Mock user existence check.
        mock_session.query.return_value.filter.return_value.first.return_value = None

        # Act.
        with patch.object(
            processor, "_process_training_readiness"
        ) as mock_process_training_readiness, patch.object(
            processor, "_ensure_user_exists", return_value=1
        ) as mock_ensure_user:
            processor.process_file_set(file_set, mock_session)

        # Assert.
        mock_process_training_readiness.assert_called_once_with(
            training_readiness_file, mock_session
        )
        mock_ensure_user.assert_called_once_with("123456789", mock_session)

    def test_process_training_readiness_null_value_handling(
        self, processor, mock_session
    ):
        """
        Test _process_training_readiness properly handles null values.

        Verifies that None/null values are included in the database record rather than
        being skipped, ensuring proper upsert functionality.

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        """

        # Arrange - data with mix of null and non-null values.
        data_with_nulls = [
            {
                "timestamp": "2025-08-07T12:00:00.0",
                "level": "MODERATE",
                "score": 50,
                "recoveryTimeChangePhrase": None,  # Explicitly null.
                "sleepScore": 77,  # Non-null.
                "hrvFactorFeedbackPhrase": None,  # Explicitly null.
                "validSleep": True,  # Non-null.
            }
        ]

        # Act.
        with patch(
            "dags.pipelines.garmin.process.upsert_model_instances"
        ) as mock_upsert:
            with patch.object(
                processor, "_load_json_file", return_value=data_with_nulls
            ):
                processor.user_id = 1
                processor._process_training_readiness(Path("dummy"), mock_session)

                # Assert.
                mock_upsert.assert_called_once()
                model_instances = mock_upsert.call_args[1]["model_instances"]
                assert len(model_instances) == 1

                # Get the TrainingReadiness instance.
                readiness_instance = model_instances[0]

                # Verify null values are included (not skipped).
                assert hasattr(
                    readiness_instance, "recovery_time_change_phrase"
                ), "Null field should be present"
                assert (
                    readiness_instance.recovery_time_change_phrase is None
                ), "Null value should be preserved"

                assert hasattr(
                    readiness_instance, "hrv_factor_feedback_phrase"
                ), "Null field should be present"
                assert (
                    readiness_instance.hrv_factor_feedback_phrase is None
                ), "Null value should be preserved"

                # Verify non-null values are also present.
                assert readiness_instance.level == "MODERATE"
                assert readiness_instance.score == 50
                assert readiness_instance.sleep_score == 77
                assert readiness_instance.valid_sleep is True

    # Stress and Body Battery Processing Tests.
    @pytest.fixture
    def sample_stress_data(self) -> Dict:
        """
        Create sample stress data with both stress and body battery arrays.

        :return: Sample stress JSON data.
        """

        return {
            "stressValuesArray": [
                [1754550000000, 25],  # Valid stress value.
                [1754550180000, 40],  # Valid stress value.
                [1754550360000, -1],  # Invalid stress value (negative).
                [1754550540000, 55],  # Valid stress value.
                [1754550720000],  # Incomplete entry.
            ],
            "bodyBatteryValuesArray": [
                [1754550000000, 0, 75],  # Valid body battery value.
                [1754550180000, 1, 72],  # Valid body battery value.
                [1754550360000, 2, 68],  # Valid body battery value.
                [1754550540000, 3],  # Incomplete entry.
            ],
            "otherData": "should be removed by pop",
        }

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_stress_body_battery_file(
        self, mock_upsert, processor, mock_session, temp_dir, sample_stress_data
    ):
        """
        Test _process_stress_body_battery method with complete data.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        :param sample_stress_data: Sample stress data fixture.
        """

        # Arrange.
        stress_file = temp_dir / "123456789_STRESS_2022-01-01T00-00-00Z.json"
        with open(stress_file, "w", encoding="utf-8") as f:
            json.dump(sample_stress_data, f)

        # Act.
        processor.user_id = 1
        processor._process_stress_body_battery(stress_file, mock_session)

        # Assert.
        # Verify upsert was called twice (stress and body battery).
        assert mock_upsert.call_count == 2

        # Get the calls and verify they are for the correct models.
        calls = mock_upsert.call_args_list

        # First call should be for stress records.
        stress_call = calls[0]
        stress_instances = stress_call[1]["model_instances"]
        assert len(stress_instances) == 3  # Only valid stress values.
        assert all(isinstance(instance, Stress) for instance in stress_instances)
        assert stress_call[1]["conflict_columns"] == ["user_id", "timestamp"]
        assert stress_call[1]["on_conflict_update"] is False

        # Second call should be for body battery records.
        battery_call = calls[1]
        battery_instances = battery_call[1]["model_instances"]
        assert len(battery_instances) == 3  # Only valid body battery values.
        assert all(isinstance(instance, BodyBattery) for instance in battery_instances)
        assert battery_call[1]["conflict_columns"] == ["user_id", "timestamp"]
        assert battery_call[1]["on_conflict_update"] is False

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_stress_values_filtering(
        self, mock_upsert, processor, mock_session, temp_dir
    ):
        """
        Test stress value filtering and timestamp conversion.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange - data with negative and incomplete values.
        stress_data = {
            "stressValuesArray": [
                [1640995200000, 30],  # Valid: 2022-01-01 00:00:00 UTC.
                [1640995380000, -5],  # Invalid: negative stress.
                [1640995560000, 0],  # Valid: zero stress.
                [1640995740000, 100],  # Valid: max stress.
                [1640995920000],  # Invalid: incomplete.
            ],
            "bodyBatteryValuesArray": [],
        }

        stress_file = temp_dir / "123456789_STRESS_2022-01-01T00-00-00Z.json"
        with open(stress_file, "w", encoding="utf-8") as f:
            json.dump(stress_data, f)

        # Act.
        processor.user_id = 1
        processor._process_stress_body_battery(stress_file, mock_session)

        # Assert.
        # Should have one call for stress (empty body battery skipped).
        mock_upsert.assert_called_once()

        stress_instances = mock_upsert.call_args[1]["model_instances"]
        assert len(stress_instances) == 3  # Only valid values.

        # Verify values and timestamps.
        stress_levels = [instance.value for instance in stress_instances]
        assert stress_levels == [30, 0, 100]

        # Verify first timestamp conversion.
        first_instance = stress_instances[0]
        expected_timestamp = datetime.fromtimestamp(
            1640995200000 / 1000, tz=timezone.utc
        )
        assert first_instance.timestamp == expected_timestamp
        assert first_instance.user_id == 1

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_body_battery_values_extraction(
        self, mock_upsert, processor, mock_session, temp_dir
    ):
        """
        Test body battery value extraction from 3-element arrays.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange - focus on body battery data.
        stress_data = {
            "stressValuesArray": [],
            "bodyBatteryValuesArray": [
                [1640995200000, 123, 85],  # timestamp, unknown, body_battery_level.
                [1640995380000, 456, 80],
                [1640995560000, 789, 75],
                [1640995740000, 999],  # Incomplete: missing body battery level.
                [1640995920000, 111, 70, 999],  # Extra data: should still work.
            ],
        }

        stress_file = temp_dir / "123456789_STRESS_2022-01-01T00-00-00Z.json"
        with open(stress_file, "w", encoding="utf-8") as f:
            json.dump(stress_data, f)

        # Act.
        processor.user_id = 1
        processor._process_stress_body_battery(stress_file, mock_session)

        # Assert.
        # Should have one call for body battery (empty stress skipped).
        mock_upsert.assert_called_once()

        battery_instances = mock_upsert.call_args[1]["model_instances"]
        assert len(battery_instances) == 4  # All complete entries.

        # Verify extracted values (third element from array).
        battery_levels = [instance.value for instance in battery_instances]
        assert battery_levels == [85, 80, 75, 70]

        # Verify timestamp conversion for first instance.
        first_instance = battery_instances[0]
        expected_timestamp = datetime.fromtimestamp(
            1640995200000 / 1000, tz=timezone.utc
        )
        assert first_instance.timestamp == expected_timestamp
        assert first_instance.user_id == 1

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_stress_body_battery_empty_arrays(
        self, mock_upsert, processor, mock_session, temp_dir
    ):
        """
        Test processing with empty stress and body battery arrays.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange - empty arrays.
        stress_data = {
            "stressValuesArray": [],
            "bodyBatteryValuesArray": [],
            "otherFields": {"ignored": True},
        }

        stress_file = temp_dir / "123456789_STRESS_2022-01-01T00-00-00Z.json"
        with open(stress_file, "w", encoding="utf-8") as f:
            json.dump(stress_data, f)

        # Act.
        processor.user_id = 1
        processor._process_stress_body_battery(stress_file, mock_session)

        # Assert.
        # No upsert calls should be made with empty data.
        mock_upsert.assert_not_called()

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_stress_body_battery_missing_arrays(
        self, mock_upsert, processor, mock_session, temp_dir
    ):
        """
        Test processing with missing stress and body battery arrays.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange - missing arrays (pop should handle gracefully).
        stress_data = {"otherData": "no stress or body battery arrays"}

        stress_file = temp_dir / "123456789_STRESS_2022-01-01T00-00-00Z.json"
        with open(stress_file, "w", encoding="utf-8") as f:
            json.dump(stress_data, f)

        # Act.
        processor.user_id = 1
        processor._process_stress_body_battery(stress_file, mock_session)

        # Assert.
        # No upsert calls should be made with missing data.
        mock_upsert.assert_not_called()

    def test_process_stress_body_battery_data_mutation(
        self, processor, mock_session, temp_dir, sample_stress_data
    ):
        """
        Test that processing uses pop() to avoid data duplication.

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        :param sample_stress_data: Sample stress data fixture.
        """

        # Arrange.
        stress_file = temp_dir / "123456789_STRESS_2022-01-01T00-00-00Z.json"
        with open(stress_file, "w", encoding="utf-8") as f:
            json.dump(sample_stress_data, f)

        # Act.
        with patch.object(
            processor, "_load_json_file", return_value=sample_stress_data.copy()
        ) as mock_load:
            processor.user_id = 1
            processor._process_stress_body_battery(stress_file, mock_session)

            # Get the data that was passed to load_json_file.
            loaded_data = mock_load.return_value

            # Verify that pop() was used (arrays should be removed).
            assert "stressValuesArray" not in loaded_data
            assert "bodyBatteryValuesArray" not in loaded_data
            assert "otherData" in loaded_data  # Other data should remain.

    def test_process_stress_body_battery_file_routing(
        self, processor, mock_session, temp_dir
    ):
        """
        Test that STRESS files are properly routed to processing method.

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        stress_file = temp_dir / "123456789_STRESS_2022-01-01T00-00-00Z.json"
        stress_file.write_text(
            '{"stressValuesArray": [], "bodyBatteryValuesArray": []}'
        )

        # Create FileSet with STRESS files.
        file_set = FileSet(files={GARMIN_FILE_TYPES.STRESS: [stress_file]})

        # Mock user existence check.
        mock_session.query.return_value.filter.return_value.first.return_value = None

        # Act.
        with patch.object(
            processor, "_process_stress_body_battery"
        ) as mock_process_stress_body_battery, patch.object(
            processor, "_ensure_user_exists", return_value=1
        ) as mock_ensure_user:
            processor.process_file_set(file_set, mock_session)

        # Assert.
        mock_process_stress_body_battery.assert_called_once_with(
            stress_file, mock_session
        )
        mock_ensure_user.assert_called_once_with("123456789", mock_session)

    def test_stress_body_battery_model_field_mapping(self):
        """
        Test that Stress and BodyBattery models have correct field mappings.
        """

        # Act - create model instances to verify field mappings.
        test_timestamp = datetime.fromtimestamp(1640995200000 / 1000, tz=timezone.utc)

        stress_instance = Stress(
            user_id=123,
            timestamp=test_timestamp,
            value=50,
        )

        body_battery_instance = BodyBattery(
            user_id=123,
            timestamp=test_timestamp,
            value=75,
        )

        # Assert - verify model fields.
        assert stress_instance.user_id == 123
        assert stress_instance.timestamp == test_timestamp
        assert stress_instance.value == 50

        assert body_battery_instance.user_id == 123
        assert body_battery_instance.timestamp == test_timestamp
        assert body_battery_instance.value == 75

    # Heart Rate Processing Tests.
    @pytest.fixture
    def sample_heart_rate_data(self) -> Dict:
        """
        Create sample heart rate data based on provided JSON structure.

        :return: Sample heart rate data dictionary.
        """

        return {
            "userProfilePK": 15007510,
            "calendarDate": "2025-08-07",
            "startTimestampGMT": "2025-08-07T07:00:00.0",
            "endTimestampGMT": "2025-08-08T07:00:00.0",
            "startTimestampLocal": "2025-08-07T00:00:00.0",
            "endTimestampLocal": "2025-08-08T00:00:00.0",
            "maxHeartRate": 183,
            "minHeartRate": 43,
            "restingHeartRate": 45,
            "lastSevenDaysAvgRestingHeartRate": 45,
            "heartRateValues": [
                [1754550000000, 49],  # Epoch timestamp in ms, heart rate value
                [1754550120000, 49],
                [1754550240000, 47],
                [1754550360000, 48],
                [1754550480000, 48],
                [1754550600000, 48],
            ],
        }

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_heart_rate_file(
        self, mock_upsert, processor, mock_session, temp_dir, sample_heart_rate_data
    ):
        """
        Test _process_heart_rate with complete data.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        :param sample_heart_rate_data: Sample heart rate data fixture.
        """

        # Arrange.
        heart_rate_file = temp_dir / "15007510_HEART_RATE_2025-08-07T12:00:00Z.json"
        with open(heart_rate_file, "w", encoding="utf-8") as f:
            json.dump(sample_heart_rate_data, f)

        # Act.
        processor.user_id = 1
        processor._process_heart_rate(heart_rate_file, mock_session)

        # Assert.
        mock_upsert.assert_called_once()
        _, kwargs = mock_upsert.call_args
        model_instances = kwargs["model_instances"]
        assert len(model_instances) == 6  # 6 heart rate measurements
        assert all(isinstance(m, HeartRate) for m in model_instances)
        assert kwargs["conflict_columns"] == ["user_id", "timestamp"]
        assert kwargs["on_conflict_update"] is False

        # Check first heart rate record.
        first_record = model_instances[0]
        assert first_record.user_id == 1
        assert first_record.value == 49
        # Verify timestamp conversion from epoch milliseconds.
        expected_timestamp = datetime.fromtimestamp(
            1754550000000 / 1000, tz=timezone.utc
        )
        assert first_record.timestamp == expected_timestamp

    def test_process_heart_rate_missing_values(self, processor, mock_session, temp_dir):
        """
        Test _process_heart_rate with missing heartRateValues.

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        data_no_values = {
            "userProfilePK": 15007510,
            "calendarDate": "2025-08-07",
            "maxHeartRate": 183,
            "minHeartRate": 43,
            # Missing heartRateValues
        }
        heart_rate_file = temp_dir / "15007510_HEART_RATE_2025-08-07T12:00:00Z.json"
        with open(heart_rate_file, "w", encoding="utf-8") as f:
            json.dump(data_no_values, f)

        # Act.
        with patch(
            "dags.pipelines.garmin.process.upsert_model_instances"
        ) as mock_upsert:
            processor.user_id = 1
            processor._process_heart_rate(heart_rate_file, mock_session)

        # Assert.
        mock_upsert.assert_not_called()  # No records should be processed

    def test_process_heart_rate_empty_values(self, processor, mock_session, temp_dir):
        """
        Test _process_heart_rate with empty heartRateValues array.

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        data_empty_values = {
            "userProfilePK": 15007510,
            "calendarDate": "2025-08-07",
            "heartRateValues": [],  # Empty array
        }
        heart_rate_file = temp_dir / "15007510_HEART_RATE_2025-08-07T12:00:00Z.json"
        with open(heart_rate_file, "w", encoding="utf-8") as f:
            json.dump(data_empty_values, f)

        # Act.
        with patch(
            "dags.pipelines.garmin.process.upsert_model_instances"
        ) as mock_upsert:
            processor.user_id = 1
            processor._process_heart_rate(heart_rate_file, mock_session)

        # Assert.
        mock_upsert.assert_not_called()  # No records should be processed

    def test_process_heart_rate_invalid_values(
        self, processor, mock_session, temp_dir, sample_heart_rate_data
    ):
        """
        Test _process_heart_rate filters out invalid values (None, null timestamps).

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        :param sample_heart_rate_data: Sample heart rate data fixture.
        """

        # Arrange - add invalid values to the data.
        modified_data = copy.deepcopy(sample_heart_rate_data)
        modified_data["heartRateValues"] = [
            [1754550000000, 49],  # Valid
            [None, 50],  # Invalid timestamp
            [1754550240000, None],  # Invalid heart rate
            [1754550360000, 48],  # Valid
            [None, None],  # Both invalid
            [1754550480000, 47],  # Valid
        ]

        heart_rate_file = temp_dir / "15007510_HEART_RATE_2025-08-07T12:00:00Z.json"
        with open(heart_rate_file, "w", encoding="utf-8") as f:
            json.dump(modified_data, f)

        # Act.
        with patch(
            "dags.pipelines.garmin.process.upsert_model_instances"
        ) as mock_upsert:
            processor.user_id = 1
            processor._process_heart_rate(heart_rate_file, mock_session)

        # Assert.
        mock_upsert.assert_called_once()
        _, kwargs = mock_upsert.call_args
        model_instances = kwargs["model_instances"]
        assert len(model_instances) == 3  # Only 3 valid records
        assert all(isinstance(m, HeartRate) for m in model_instances)

        # Check that only valid records are included.
        heart_rate_values = [record.value for record in model_instances]
        assert heart_rate_values == [49, 48, 47]

    def test_process_heart_rate_file_routing(self, processor, mock_session, temp_dir):
        """
        Test that HEART_RATE files are properly routed to processing method.

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        heart_rate_file = temp_dir / "123456789_HEART_RATE_2022-01-01T00:00:00Z.json"
        heart_rate_file.write_text('{"heartRateValues": [[1640995200000, 65]]}')

        # Create FileSet with HEART_RATE files.
        file_set = FileSet(files={GARMIN_FILE_TYPES.HEART_RATE: [heart_rate_file]})

        # Mock user existence check.
        mock_session.query.return_value.filter.return_value.first.return_value = None

        # Act.
        with patch.object(
            processor, "_process_heart_rate"
        ) as mock_process_heart_rate, patch.object(
            processor, "_ensure_user_exists", return_value=1
        ) as mock_ensure_user:
            processor.process_file_set(file_set, mock_session)

        # Assert.
        mock_process_heart_rate.assert_called_once_with(heart_rate_file, mock_session)
        mock_ensure_user.assert_called_once_with("123456789", mock_session)

    @pytest.fixture
    def sample_respiration_data(self) -> Dict:
        """
        Create sample respiration data based on provided JSON structure.

        :return: Sample respiration data dictionary.
        """

        return {
            "userProfilePK": 15007510,
            "calendarDate": "2025-08-07",
            "startTimestampGMT": "2025-08-07T07:00:00.0",
            "endTimestampGMT": "2025-08-08T07:00:00.0",
            "startTimestampLocal": "2025-08-07T00:00:00.0",
            "endTimestampLocal": "2025-08-08T00:00:00.0",
            "sleepStartTimestampGMT": "2025-08-07T06:42:06.0",
            "sleepEndTimestampGMT": "2025-08-07T13:23:06.0",
            "sleepStartTimestampLocal": "2025-08-06T23:42:06.0",
            "sleepEndTimestampLocal": "2025-08-07T06:23:06.0",
            "lowestRespirationValue": 6.0,
            "highestRespirationValue": 45.0,
            "avgWakingRespirationValue": 15.0,
            "avgSleepRespirationValue": 11.0,
            "avgTomorrowSleepRespirationValue": 11.0,
            "respirationValueDescriptorsDTOList": [
                {"key": "timestamp", "index": 0},
                {"key": "respiration", "index": 1},
            ],
            "respirationValuesArray": [
                [1754550120000, 11.0],  # Epoch timestamp in ms, respiration value
                [1754550240000, 12.0],
                [1754550360000, 13.0],
                [1754550480000, 11.0],
                [1754557680000, -1.0],  # Negative value (should be skipped)
                [1754557800000, 13.0],
                [1754557920000, 10.0],
            ],
            "respirationAveragesValueDescriptorDTOList": [
                {
                    "respirationAveragesValueDescriptorIndex": 0,
                    "respirationAveragesValueDescriptionKey": "timestamp",
                },
                {
                    "respirationAveragesValueDescriptorIndex": 1,
                    "respirationAveragesValueDescriptionKey": "averageRespirationValue",
                },
            ],
            "respirationAveragesValuesArray": [
                [1754553600000, 11.74, 17.0, 7.0],
                [1754557200000, 11.05, 15.0, 7.0],
            ],
            "respirationVersion": 200,
        }

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_respiration_file(
        self, mock_upsert, processor, mock_session, temp_dir, sample_respiration_data
    ):
        """
        Test _process_respiration with complete data.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        :param sample_respiration_data: Sample respiration data fixture.
        """

        # Arrange.
        respiration_file = temp_dir / "15007510_RESPIRATION_2025-08-07T12:00:00Z.json"
        with open(respiration_file, "w", encoding="utf-8") as f:
            json.dump(sample_respiration_data, f)

        # Act.
        processor.user_id = 1
        processor._process_respiration(respiration_file, mock_session)

        # Assert.
        mock_upsert.assert_called_once()
        _, kwargs = mock_upsert.call_args
        model_instances = kwargs["model_instances"]
        # Should be 6 records (7 total - 1 negative value filtered out)
        assert len(model_instances) == 6
        assert all(isinstance(m, Respiration) for m in model_instances)
        assert kwargs["conflict_columns"] == ["user_id", "timestamp"]
        assert kwargs["on_conflict_update"] is False

        # Check first respiration record.
        first_record = model_instances[0]
        assert first_record.user_id == 1
        assert first_record.value == 11.0
        # Verify timestamp conversion from epoch milliseconds.
        expected_timestamp = datetime.fromtimestamp(
            1754550120000 / 1000, tz=timezone.utc
        )
        assert first_record.timestamp == expected_timestamp

    def test_process_respiration_missing_values(
        self, processor, mock_session, temp_dir
    ):
        """
        Test _process_respiration with missing respirationValuesArray.

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        data_no_values = {
            "userProfilePK": 15007510,
            "calendarDate": "2025-08-07",
            "lowestRespirationValue": 6.0,
            "highestRespirationValue": 45.0,
            # Missing respirationValuesArray
        }

        respiration_file = temp_dir / "15007510_RESPIRATION_2025-08-07T12:00:00Z.json"
        with open(respiration_file, "w", encoding="utf-8") as f:
            json.dump(data_no_values, f)

        # Act and Assert.
        with patch("dags.lib.logging_utils.LOGGER.warning") as mock_logger:
            processor.user_id = 1
            processor._process_respiration(respiration_file, mock_session)
            mock_logger.assert_called_with("⚠️ No respiration data found.")

    def test_process_respiration_empty_values(self, processor, mock_session, temp_dir):
        """
        Test _process_respiration with empty respirationValuesArray.

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        data_empty_values = {
            "userProfilePK": 15007510,
            "calendarDate": "2025-08-07",
            "respirationValuesArray": [],  # Empty array
        }

        respiration_file = temp_dir / "15007510_RESPIRATION_2025-08-07T12:00:00Z.json"
        with open(respiration_file, "w", encoding="utf-8") as f:
            json.dump(data_empty_values, f)

        # Act and Assert.
        with patch("dags.lib.logging_utils.LOGGER.warning") as mock_logger:
            processor.user_id = 1
            processor._process_respiration(respiration_file, mock_session)
            mock_logger.assert_called_with("⚠️ No respiration data found.")

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_respiration_invalid_values(
        self, mock_upsert, processor, mock_session, temp_dir
    ):
        """
        Test _process_respiration with invalid and negative respiration values.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        data_invalid_values = {
            "userProfilePK": 15007510,
            "calendarDate": "2025-08-07",
            "respirationValuesArray": [
                [1754550120000, -1.0],  # Negative - should be filtered out
                [1754550240000, -2.0],  # Negative - should be filtered out
                [1754550360000, 12.0],  # Valid
                [1754550480000, 15.0],  # Valid
                [1754550600000],  # Invalid format - missing respiration value
                [],  # Invalid format - empty array
                [1754550720000, 0.0],  # Valid (zero is acceptable)
                [1754550840000, 13.5],  # Valid float
            ],
        }

        respiration_file = temp_dir / "15007510_RESPIRATION_2025-08-07T12:00:00Z.json"
        with open(respiration_file, "w", encoding="utf-8") as f:
            json.dump(data_invalid_values, f)

        # Act.
        processor.user_id = 1
        processor._process_respiration(respiration_file, mock_session)

        # Assert.
        mock_upsert.assert_called_once()
        _, kwargs = mock_upsert.call_args
        model_instances = kwargs["model_instances"]
        # Should be 4 valid records (ignoring negatives, malformed entries)
        assert len(model_instances) == 4

        # Check values are as expected.
        values = [record.value for record in model_instances]
        assert values == [12.0, 15.0, 0.0, 13.5]

    @patch("dags.lib.sql_utils.upsert_model_instances")
    def test_process_respiration_no_valid_records(
        self, mock_upsert, processor, mock_session, temp_dir
    ):
        """
        Test _process_respiration when all values are invalid/negative.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        data_no_valid_values = {
            "userProfilePK": 15007510,
            "calendarDate": "2025-08-07",
            "respirationValuesArray": [
                [1754550120000, -1.0],  # Negative
                [1754550240000, -2.0],  # Negative
                [],  # Empty
                [1754550360000],  # Missing value
            ],
        }

        respiration_file = temp_dir / "15007510_RESPIRATION_2025-08-07T12:00:00Z.json"
        with open(respiration_file, "w", encoding="utf-8") as f:
            json.dump(data_no_valid_values, f)

        # Act and Assert.
        with patch("dags.lib.logging_utils.LOGGER.warning") as mock_logger:
            processor.user_id = 1
            processor._process_respiration(respiration_file, mock_session)
            mock_logger.assert_called_with("⚠️ No respiration data found.")
            # upsert should not be called when no valid records.
            mock_upsert.assert_not_called()

    def test_process_respiration_file_routing(self, processor, mock_session, temp_dir):
        """
        Test that RESPIRATION files are routed to _process_respiration.

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        respiration_file = temp_dir / "123456789_RESPIRATION_2025-08-07T12:00:00Z.json"
        minimal_data = {
            "userProfilePK": 123456789,
            "respirationValuesArray": [[1754550120000, 12.0]],
        }
        with open(respiration_file, "w", encoding="utf-8") as f:
            json.dump(minimal_data, f)

        file_set = FileSet(files={GARMIN_FILE_TYPES.RESPIRATION: [respiration_file]})

        # Act.
        with patch.object(
            processor, "_process_respiration"
        ) as mock_process_respiration, patch.object(
            processor, "_ensure_user_exists", return_value=1
        ) as mock_ensure_user:
            processor.process_file_set(file_set, mock_session)

        # Assert.
        mock_process_respiration.assert_called_once_with(respiration_file, mock_session)
        mock_ensure_user.assert_called_once_with("123456789", mock_session)

    # Intensity minutes tests.
    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_intensity_minutes_file(
        self, mock_upsert, processor, mock_session, temp_dir
    ):
        """
        Test _process_intensity_minutes with complete data.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        intensity_data = {
            "userProfilePK": 15007510,
            "calendarDate": "2025-08-07",
            "startTimestampGMT": "2025-08-07T07:00:00.0",
            "endTimestampGMT": "2025-08-08T07:00:00.0",
            "startDayMinutes": 250,
            "endDayMinutes": 365,
            "moderateMinutes": 21,
            "vigorousMinutes": 47,
            "imValuesArray": [
                [1754576100000, 3],
                [1754577000000, 28],
                [1754577900000, 25],
                [1754578800000, 29],
                [1754579700000, 19],
                [1754580600000, 11],
            ],
        }

        intensity_file = (
            temp_dir / "15007510_INTENSITY_MINUTES_2025-08-07T12:00:00Z.json"
        )
        with open(intensity_file, "w", encoding="utf-8") as f:
            json.dump(intensity_data, f)

        # Act.
        processor.user_id = 1
        processor._process_intensity_minutes(intensity_file, mock_session)

        # Assert.
        # Should have 2 upsert calls: 1 for intensity minutes + 1 for training load.
        assert mock_upsert.call_count == 2

        # First call should be intensity minutes.
        intensity_call = mock_upsert.call_args_list[0]
        assert intensity_call[1]["session"] == mock_session
        assert intensity_call[1]["conflict_columns"] == ["user_id", "timestamp"]
        assert intensity_call[1]["on_conflict_update"] is False
        assert len(intensity_call[1]["model_instances"]) == 6

        # Second call should be training load.
        training_load_call = mock_upsert.call_args_list[1]
        assert training_load_call[1]["session"] == mock_session
        assert training_load_call[1]["conflict_columns"] == ["user_id", "date"]
        assert training_load_call[1]["on_conflict_update"] is True
        assert len(training_load_call[1]["model_instances"]) == 1

        # Verify training load record details.
        training_load_record = training_load_call[1]["model_instances"][0]
        assert training_load_record.user_id == 1
        assert training_load_record.date == "2025-08-07"
        assert training_load_record.moderate_minutes == 21
        assert training_load_record.vigorous_minutes == 47
        assert training_load_record.total_intensity_minutes == 115  # 365 - 250

        # No session.merge calls.
        assert mock_session.merge.call_count == 0

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_intensity_minutes_missing_values(
        self, mock_upsert, processor, mock_session, temp_dir
    ):
        """
        Test _process_intensity_minutes with missing imValuesArray.

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        data_no_values = {
            "userProfilePK": 15007510,
            "calendarDate": "2025-08-07",
            "moderateMinutes": 21,
            "vigorousMinutes": 47,
            # Missing imValuesArray
        }

        intensity_file = (
            temp_dir / "15007510_INTENSITY_MINUTES_2025-08-07T12:00:00Z.json"
        )
        with open(intensity_file, "w", encoding="utf-8") as f:
            json.dump(data_no_values, f)

        # Act and Assert.
        with patch("dags.lib.logging_utils.LOGGER.warning") as mock_logger:
            processor.user_id = 1
            processor._process_intensity_minutes(intensity_file, mock_session)
            mock_logger.assert_called_with("⚠️ No intensity minutes data found.")

        # Should still process training_load data (1 upsert call).
        mock_upsert.assert_called_once()
        call_args = mock_upsert.call_args
        assert call_args[1]["session"] == mock_session
        assert call_args[1]["conflict_columns"] == ["user_id", "date"]
        assert call_args[1]["on_conflict_update"] is True
        assert len(call_args[1]["model_instances"]) == 1
        assert mock_session.merge.call_count == 0  # No immediate merge calls.

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_intensity_minutes_invalid_values(
        self, mock_upsert, processor, mock_session, temp_dir
    ):
        """
        Test _process_intensity_minutes with invalid and negative intensity values.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        data_invalid_values = {
            "userProfilePK": 15007510,
            "calendarDate": "2025-08-07",
            "imValuesArray": [
                [1754576100000, -1],  # Negative - should be filtered out.
                [1754577000000, -2],  # Negative - should be filtered out.
                [1754577900000, 25],  # Valid.
                [1754578800000, 29],  # Valid.
                [1754579700000],  # Invalid format - missing intensity value.
                [],  # Invalid format - empty array.
                [1754580600000, 0],  # Valid (zero is acceptable).
                [1754581500000, 15],  # Valid.
            ],
        }

        intensity_file = (
            temp_dir / "15007510_INTENSITY_MINUTES_2025-08-07T12:00:00Z.json"
        )
        with open(intensity_file, "w", encoding="utf-8") as f:
            json.dump(data_invalid_values, f)

        # Act.
        processor.user_id = 1
        processor._process_intensity_minutes(intensity_file, mock_session)

        # Assert.
        # Should have 1 upsert call for intensity minutes only (no training load data).
        mock_upsert.assert_called_once()
        call_args = mock_upsert.call_args

        # Should only process 4 valid intensity minute records (25, 29, 0, 15).
        assert call_args[1]["conflict_columns"] == ["user_id", "timestamp"]
        assert len(call_args[1]["model_instances"]) == 4

        # Verify the valid records.
        records = call_args[1]["model_instances"]
        values = [record.value for record in records]
        assert 25 in values
        assert 29 in values
        assert 0 in values
        assert 15 in values

    def test_process_intensity_minutes_file_routing(
        self, processor, mock_session, temp_dir
    ):
        """
        Test that INTENSITY_MINUTES files are routed to _process_intensity_minutes.

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        intensity_file = (
            temp_dir / "123456789_INTENSITY_MINUTES_2025-08-07T12:00:00Z.json"
        )
        minimal_data = {
            "userProfilePK": 123456789,
            "imValuesArray": [[1754576100000, 12]],
        }
        with open(intensity_file, "w", encoding="utf-8") as f:
            json.dump(minimal_data, f)

        file_set = FileSet(
            files={GARMIN_FILE_TYPES.INTENSITY_MINUTES: [intensity_file]}
        )

        # Act.
        with patch.object(
            processor, "_process_intensity_minutes"
        ) as mock_process_intensity_minutes, patch.object(
            processor, "_ensure_user_exists", return_value=1
        ) as mock_ensure_user:
            processor.process_file_set(file_set, mock_session)

        # Assert.
        mock_process_intensity_minutes.assert_called_once_with(
            intensity_file, mock_session
        )
        mock_ensure_user.assert_called_once_with("123456789", mock_session)

    # Floors tests.
    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_floors_file(self, mock_upsert, processor, mock_session, temp_dir):
        """
        Test _process_floors with complete data.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        floors_data = {
            "userProfilePK": 15007510,
            "startTimestampGMT": "2025-08-07T07:00:00.0",
            "endTimestampGMT": "2025-08-08T07:00:00.0",
            "floorsValueDescriptorDTOList": [
                {"key": "startTimeGMT", "index": 0},
                {"key": "endTimeGMT", "index": 1},
                {"key": "floorsAscended", "index": 2},
                {"key": "floorsDescended", "index": 3},
            ],
            "floorValuesArray": [
                ["2025-08-07T14:15:00.0", "2025-08-07T14:30:00.0", 1, 0],
                ["2025-08-07T14:30:00.0", "2025-08-07T14:45:00.0", 0, 1],
                ["2025-08-07T15:00:00.0", "2025-08-07T15:15:00.0", 1, 1],
                ["2025-08-07T15:30:00.0", "2025-08-07T15:45:00.0", 1, 1],
            ],
        }

        floors_file = temp_dir / "15007510_FLOORS_2025-08-07T12:00:00Z.json"
        with open(floors_file, "w", encoding="utf-8") as f:
            json.dump(floors_data, f)

        # Act.
        processor.user_id = 1
        processor._process_floors(floors_file, mock_session)

        # Assert.
        mock_upsert.assert_called_once()
        call_args = mock_upsert.call_args
        assert call_args[1]["session"] == mock_session
        assert call_args[1]["conflict_columns"] == ["user_id", "timestamp"]
        assert call_args[1]["on_conflict_update"] is False
        assert len(call_args[1]["model_instances"]) == 4

        # Verify floors data in model instances.
        floors_records = call_args[1]["model_instances"]
        assert floors_records[0].user_id == 1
        assert floors_records[0].ascended == 1
        assert floors_records[0].descended == 0
        assert floors_records[1].ascended == 0
        assert floors_records[1].descended == 1

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_floors_missing_values(
        self, mock_upsert, processor, mock_session, temp_dir
    ):
        """
        Test _process_floors with missing floorValuesArray.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        floors_data = {
            "userProfilePK": 15007510,
            "startTimestampGMT": "2025-08-07T07:00:00.0",
            "endTimestampGMT": "2025-08-08T07:00:00.0",
        }

        floors_file = temp_dir / "15007510_FLOORS_2025-08-07T12:00:00Z.json"
        with open(floors_file, "w", encoding="utf-8") as f:
            json.dump(floors_data, f)

        # Act.
        processor.user_id = 1
        processor._process_floors(floors_file, mock_session)

        # Assert.
        mock_upsert.assert_not_called()

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_floors_invalid_values(
        self, mock_upsert, processor, mock_session, temp_dir
    ):
        """
        Test _process_floors with invalid floor value arrays.

        :param mock_upsert: Mock upsert function.
        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        floors_data = {
            "userProfilePK": 15007510,
            "floorValuesArray": [
                ["2025-08-07T14:15:00.0"],  # Missing values.
                [
                    "2025-08-07T14:30:00.0",
                    "2025-08-07T14:45:00.0",
                ],  # Missing ascended/descended.
                ["2025-08-07T15:00:00.0", "2025-08-07T15:15:00.0", 2, 1],  # Valid.
            ],
        }

        floors_file = temp_dir / "15007510_FLOORS_2025-08-07T12:00:00Z.json"
        with open(floors_file, "w", encoding="utf-8") as f:
            json.dump(floors_data, f)

        # Act.
        processor.user_id = 1
        processor._process_floors(floors_file, mock_session)

        # Assert.
        mock_upsert.assert_called_once()
        call_args = mock_upsert.call_args
        assert len(call_args[1]["model_instances"]) == 1

    def test_process_floors_file_routing(self, processor, mock_session, temp_dir):
        """
        Test that FLOORS files are routed to _process_floors.

        :param processor: GarminProcessor fixture.
        :param mock_session: Mock session fixture.
        :param temp_dir: Temporary directory fixture.
        """

        # Arrange.
        floors_file = temp_dir / "123456789_FLOORS_2025-08-07T12:00:00Z.json"
        minimal_data = {
            "userProfilePK": 123456789,
            "floorValuesArray": [
                ["2025-08-07T15:00:00.0", "2025-08-07T15:15:00.0", 1, 0]
            ],
        }
        with open(floors_file, "w", encoding="utf-8") as f:
            json.dump(minimal_data, f)

        file_set = FileSet(files={GARMIN_FILE_TYPES.FLOORS: [floors_file]})

        # Act.
        with patch.object(
            processor, "_process_floors"
        ) as mock_process_floors, patch.object(
            processor, "_ensure_user_exists", return_value=1
        ) as mock_ensure_user:
            processor.process_file_set(file_set, mock_session)

        # Assert.
        mock_process_floors.assert_called_once_with(floors_file, mock_session)
        mock_ensure_user.assert_called_once_with("123456789", mock_session)

    @pytest.fixture
    def sample_personal_records_data(self) -> List[Dict]:
        """
        Sample personal records data for testing.
        """

        return [
            {
                "id": 2071637774,
                "typeId": 3,
                "status": "ACCEPTED",
                "activityId": 8649918243,
                "activityName": "TT 5k",
                "activityType": "running",
                "value": 1091.7960205078125,
                "prStartTimeGmt": 1650114005000,
                "prStartTimeGmtFormatted": "2022-04-16T13:00:05.0",
                "prStartTimeLocal": None,
                "prStartTimeLocalFormatted": None,
                "prTypeLabelKey": None,
                "poolLengthUnit": None,
            },
            {
                "id": 1619773303,
                "typeId": 4,
                "status": "ACCEPTED",
                "activityId": 4914160155,
                "activityName": "Prog tempo",
                "activityType": "running",
                "value": 2441.117919921875,
                "prStartTimeGmt": 1589158420000,
                "prStartTimeGmtFormatted": "2020-05-11T00:53:40.0",
                "prStartTimeLocal": None,
                "prStartTimeLocalFormatted": None,
                "prTypeLabelKey": None,
                "poolLengthUnit": None,
            },
            {
                "id": 2030060315,
                "typeId": 7,
                "status": "ACCEPTED",
                "activityId": 8110297915,
                "activityName": "Long run",
                "activityType": "running",
                "value": 21018.83984375,
                "prStartTimeGmt": 1642071671000,
                "prStartTimeGmtFormatted": "2022-01-13T11:01:11.0",
                "prStartTimeLocal": None,
                "prStartTimeLocalFormatted": None,
                "prTypeLabelKey": None,
                "poolLengthUnit": None,
            },
        ]

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_personal_records_file(
        self,
        mock_upsert,
        processor,
        mock_session,
        temp_dir,
        sample_personal_records_data,
    ):
        """
        Test _process_personal_records with complete personal records data.
        """

        # Arrange.
        pr_file = temp_dir / "123456789_PERSONAL_RECORDS_2025-08-07T12:00:00Z.json"
        with open(pr_file, "w", encoding="utf-8") as f:
            json.dump(sample_personal_records_data, f)

        user_id = 1
        processor.user_id = user_id

        # Mock session queries.
        def mock_query_side_effect(model):
            query_mock = MagicMock()

            if model == Activity:
                # Mock Activity queries - all activities exist for this test.
                query_mock.filter.return_value.first.return_value = (
                    MagicMock()
                )  # Activity exists.

            elif model == PersonalRecord:
                # Mock PersonalRecord queries - no existing records.
                query_mock.filter.return_value.all.return_value = []

            return query_mock

        mock_session.query.side_effect = mock_query_side_effect

        # Act.
        processor._process_personal_records(pr_file, mock_session)

        # Assert.
        assert mock_upsert.call_count == 1
        call_args = mock_upsert.call_args[1]

        # Verify model instances.
        model_instances = call_args["model_instances"]
        assert len(model_instances) == 3

        # Check first record.
        first_record = model_instances[0]
        assert isinstance(first_record, PersonalRecord)
        assert first_record.user_id == 1
        assert first_record.activity_id == 8649918243
        assert first_record.type_id == 3
        assert first_record.label == "Run: 5 km"
        assert first_record.value == 1091.7960205078125
        assert first_record.latest is True

        # Check timestamp conversion.
        expected_timestamp = datetime.fromtimestamp(
            1650114005000 / 1000, tz=timezone.utc
        )
        assert first_record.timestamp == expected_timestamp

        # Verify upsert parameters match new primary key.
        assert call_args["conflict_columns"] == [
            "user_id",
            "type_id",
            "timestamp",
        ]
        assert call_args["on_conflict_update"] is True

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_personal_records_with_latest_logic(
        self, mock_upsert, processor, mock_session, temp_dir
    ):
        """
        Test _process_personal_records with latest flag management.
        """

        # Arrange.
        sample_data = [
            {
                "typeId": 3,
                "activityId": 12345,
                "value": 1200.0,
                "prStartTimeGmt": 1650114005000,
            }
        ]

        pr_file = temp_dir / "123456789_PERSONAL_RECORDS_2025-08-07T12:00:00Z.json"
        with open(pr_file, "w", encoding="utf-8") as f:
            json.dump(sample_data, f)

        user_id = 1
        processor.user_id = user_id

        # Mock existing latest records.
        existing_record1 = MagicMock()
        existing_record1.latest = True
        existing_record2 = MagicMock()
        existing_record2.latest = True
        existing_records = [existing_record1, existing_record2]

        # Mock the query to return existing records for each type_id.
        mock_query = MagicMock()
        mock_query.filter.return_value.all.return_value = existing_records
        mock_session.query.return_value = mock_query

        # Act.
        processor._process_personal_records(pr_file, mock_session)

        # Assert.
        # Verify existing records were set to latest=False.
        assert existing_record1.latest is False
        assert existing_record2.latest is False

        # Verify new record is created with latest=True.
        model_instances = mock_upsert.call_args[1]["model_instances"]
        assert len(model_instances) == 1
        assert model_instances[0].latest is True

    def test_process_personal_records_missing_data(
        self, processor, mock_session, temp_dir
    ):
        """
        Test _process_personal_records with missing essential data.
        """

        # Arrange.
        incomplete_data = [
            {"typeId": 3, "activityId": 12345},  # Missing prStartTimeGmt and value.
            {"typeId": 4, "value": 1200.0},  # Missing prStartTimeGmt and activityId.
            {
                "activityId": 67890,
                "value": 1500.0,
            },  # Missing typeId and prStartTimeGmt.
        ]

        pr_file = temp_dir / "123456789_PERSONAL_RECORDS_2025-08-07T12:00:00Z.json"
        with open(pr_file, "w", encoding="utf-8") as f:
            json.dump(incomplete_data, f)

        user_id = 1
        processor.user_id = user_id

        # Act & Assert - should raise KeyError for missing required fields.
        with pytest.raises(KeyError):
            processor._process_personal_records(pr_file, mock_session)

    def test_process_personal_records_invalid_format(
        self, processor, mock_session, temp_dir
    ):
        """
        Test _process_personal_records with invalid JSON format.
        """

        # Arrange.
        pr_file = temp_dir / "123456789_PERSONAL_RECORDS_2025-08-07T12:00:00Z.json"
        with open(pr_file, "w", encoding="utf-8") as f:
            json.dump({"not": "a list"}, f)

        user_id = 1
        processor.user_id = user_id

        # Act & Assert - should raise AttributeError for invalid data format.
        with pytest.raises(AttributeError):
            processor._process_personal_records(pr_file, mock_session)

    def test_process_personal_records_unknown_type_id(
        self, processor, mock_session, temp_dir
    ):
        """
        Test _process_personal_records with unknown type_id.
        """

        # Arrange.
        sample_data = [
            {
                "typeId": 999,  # Unknown type_id.
                "activityId": 12345,
                "value": 1200.0,
                "prStartTimeGmt": 1650114005000,
            }
        ]

        pr_file = temp_dir / "123456789_PERSONAL_RECORDS_2025-08-07T12:00:00Z.json"
        with open(pr_file, "w", encoding="utf-8") as f:
            json.dump(sample_data, f)

        user_id = 1
        processor.user_id = user_id

        # Mock session queries.
        def mock_query_side_effect(model):
            query_mock = MagicMock()

            if model == Activity:
                # Mock Activity queries - activity exists for this test.
                query_mock.filter.return_value.first.return_value = (
                    MagicMock()
                )  # Activity exists.

            elif model == PersonalRecord:
                # Mock PersonalRecord queries - no existing records.
                query_mock.filter.return_value.all.return_value = []

            return query_mock

        mock_session.query.side_effect = mock_query_side_effect

        # Act.
        with patch(
            "dags.pipelines.garmin.process.upsert_model_instances"
        ) as mock_upsert:
            processor._process_personal_records(pr_file, mock_session)

        # Assert.
        assert mock_upsert.called
        model_instances = mock_upsert.call_args[1]["model_instances"]
        assert len(model_instances) == 1
        assert (
            model_instances[0].label is None
        )  # Unknown type_id should result in None label.

    def test_process_personal_records_file_routing(
        self, processor, mock_session, temp_dir
    ):
        """
        Test that PERSONAL_RECORDS files are properly routed to processing method.
        """

        # Arrange.
        pr_file = temp_dir / "123456789_PERSONAL_RECORDS_2025-08-07T12:00:00Z.json"
        with open(pr_file, "w", encoding="utf-8") as f:
            json.dump([], f)

        file_set = FileSet(files={GARMIN_FILE_TYPES.PERSONAL_RECORDS: [pr_file]})

        # Act.
        with patch.object(
            processor, "_process_personal_records"
        ) as mock_process_pr, patch.object(
            processor, "_ensure_user_exists", return_value=1
        ) as mock_ensure_user:
            processor.process_file_set(file_set, mock_session)

        # Assert.
        mock_process_pr.assert_called_once_with(pr_file, mock_session)
        mock_ensure_user.assert_called_once_with("123456789", mock_session)

    def test_personal_record_label_mapping(self):
        """
        Test that personal record type labels are correctly mapped.
        """

        # Verify some key mappings from the prompt.
        assert PR_TYPE_LABELS[1] == "Run: 1 km"
        assert PR_TYPE_LABELS[3] == "Run: 5 km"
        assert PR_TYPE_LABELS[7] == "Run: Longest"
        assert PR_TYPE_LABELS[12] == "Steps: Most in a Day"
        assert PR_TYPE_LABELS[17] == "Swim: Longest"

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_personal_records_with_missing_activity(
        self, mock_upsert, processor, mock_session, temp_dir
    ):
        """
        Test _process_personal_records with missing activities (backfill scenario).

        This test simulates the backfill scenario where personal records reference
        activity IDs that don't exist in the database yet, ensuring proper handling by
        skipping those records and logging appropriate warnings.
        """

        # Arrange.
        sample_data = [
            {
                "typeId": 1,
                "activityId": 12345,  # This activity doesn't exist.
                "prStartTimeGmt": 1691404800000,  # Aug 7, 2023 12:00:00 GMT
                "value": 180.5,
            },
            {
                "typeId": 3,
                "activityId": 54321,  # This activity exists.
                "prStartTimeGmt": 1691404800000,  # Aug 7, 2023 12:00:00 GMT
                "value": 1200.0,
            },
            {
                "typeId": 7,
                "activityId": 99999,  # This activity doesn't exist.
                "prStartTimeGmt": 1691404800000,  # Aug 7, 2023 12:00:00 GMT
                "value": 3600.0,
            },
        ]

        pr_file = temp_dir / "123456789_PERSONAL_RECORDS_2025-08-07T12:00:00Z.json"
        with open(pr_file, "w", encoding="utf-8") as f:
            json.dump(sample_data, f)

        # Mock session queries.
        def mock_query_side_effect(model):
            query_mock = MagicMock()

            if model == Activity:
                # Mock Activity queries - only 54321 exists.
                def activity_filter_side_effect(condition):
                    # Check the actual activity_id value in the condition.
                    if (
                        hasattr(condition, "right")
                        and hasattr(condition.right, "value")
                        and condition.right.value == 54321
                    ):
                        query_mock.first.return_value = MagicMock()  # Activity exists.
                    else:
                        query_mock.first.return_value = None  # Activity doesn't exist.
                    return query_mock

                query_mock.filter.side_effect = activity_filter_side_effect

            elif model == PersonalRecord:
                # Mock PersonalRecord queries - no existing records.
                query_mock.filter.return_value.all.return_value = []

            return query_mock

        mock_session.query.side_effect = mock_query_side_effect

        # Set processor user_id.
        processor.user_id = "123456789"

        # Act.
        with patch("dags.pipelines.garmin.process.LOGGER") as mock_logger:
            processor._process_personal_records(pr_file, mock_session)

        # Assert - Only 1 record should be processed (activity_id 54321).
        assert mock_upsert.called
        call_args = mock_upsert.call_args[1]
        model_instances = call_args["model_instances"]
        assert len(model_instances) == 1
        assert model_instances[0].activity_id == 54321
        assert model_instances[0].type_id == 3

        # Assert - Warning messages logged for missing activities.
        warning_calls = [
            call
            for call in mock_logger.warning.call_args_list
            if "Skipping personal record for `activity_id`" in str(call)
        ]
        assert len(warning_calls) == 2  # Two activities missing.

        # Assert - Info message includes skip count.
        info_calls = [
            call
            for call in mock_logger.info.call_args_list
            if "Skipped 2 records with missing activities" in str(call)
        ]
        assert len(info_calls) == 1

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_personal_records_all_activities_missing(
        self, mock_upsert, processor, mock_session, temp_dir
    ):
        """
        Test _process_personal_records when all activities are missing (full backfill
        scenario).

        This test simulates a backfill scenario where none of the referenced activities
        exist in the database, ensuring all records are skipped with appropriate
        logging.
        """

        # Arrange.
        sample_data = [
            {
                "typeId": 1,
                "activityId": 12345,  # This activity doesn't exist.
                "prStartTimeGmt": 1691404800000,  # Aug 7, 2023 12:00:00 GMT
                "value": 180.5,
            },
            {
                "typeId": 3,
                "activityId": 54321,  # This activity doesn't exist.
                "prStartTimeGmt": 1691404800000,  # Aug 7, 2023 12:00:00 GMT
                "value": 1200.0,
            },
        ]

        pr_file = temp_dir / "123456789_PERSONAL_RECORDS_2025-08-07T12:00:00Z.json"
        with open(pr_file, "w", encoding="utf-8") as f:
            json.dump(sample_data, f)

        # Mock session queries.
        def mock_query_side_effect(model):
            query_mock = MagicMock()

            if model == Activity:
                # Mock Activity queries - no activities exist.
                query_mock.filter.return_value.first.return_value = None

            elif model == PersonalRecord:
                # Mock PersonalRecord queries - no existing records.
                query_mock.filter.return_value.all.return_value = []

            return query_mock

        mock_session.query.side_effect = mock_query_side_effect

        # Set processor user_id.
        processor.user_id = "123456789"

        # Act.
        with patch("dags.pipelines.garmin.process.LOGGER") as mock_logger:
            processor._process_personal_records(pr_file, mock_session)

        # Assert - No records should be processed.
        assert not mock_upsert.called

        # Assert - Warning messages logged for missing activities.
        warning_calls = [
            call
            for call in mock_logger.warning.call_args_list
            if "Skipping personal record for `activity_id`" in str(call)
        ]
        assert len(warning_calls) == 2  # Both activities missing.

        # Assert - Warning message for no records processed.
        warning_calls = [
            call
            for call in mock_logger.warning.call_args_list
            if "No personal records processed. Skipped 2 records" in str(call)
        ]
        assert len(warning_calls) == 1

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_personal_records_with_steps_records(
        self, mock_upsert, processor, mock_session, temp_dir
    ):
        """
        Test _process_personal_records with steps records (typeId 12-16).

        Steps records should have activity_id set to NULL since they represent
        daily/weekly/monthly aggregates not tied to specific activities.
        """

        # Arrange.
        sample_data = [
            {
                "typeId": 3,  # Run: 5 km (activity-based)
                "activityId": 12345,
                "prStartTimeGmt": 1691404800000,
                "value": 1200.0,
            },
            {
                "typeId": 12,  # Steps: Most in a Day (steps-based)
                "activityId": 0,  # This should become NULL
                "prStartTimeGmt": 1691404800000,
                "value": 15000.0,
            },
            {
                "typeId": 13,  # Steps: Most in a Week (steps-based)
                "activityId": 0,  # This should become NULL
                "prStartTimeGmt": 1691404800000,
                "value": 85000.0,
            },
            {
                "typeId": 16,  # Steps: Unknown Type (steps-based)
                "activityId": 0,  # This should become NULL
                "prStartTimeGmt": 1691404800000,
                "value": 0.0,
            },
        ]

        pr_file = temp_dir / "123456789_PERSONAL_RECORDS_2025-08-07T12:00:00Z.json"
        with open(pr_file, "w", encoding="utf-8") as f:
            json.dump(sample_data, f)

        # Mock session queries.
        def mock_query_side_effect(model):
            query_mock = MagicMock()

            if model == Activity:
                # Mock Activity queries - activity 12345 exists.
                def activity_filter_side_effect(condition):
                    if (
                        hasattr(condition, "right")
                        and hasattr(condition.right, "value")
                        and condition.right.value == 12345
                    ):
                        query_mock.first.return_value = MagicMock()  # Activity exists.
                    else:
                        query_mock.first.return_value = None  # Activity doesn't exist.
                    return query_mock

                query_mock.filter.side_effect = activity_filter_side_effect

            elif model == PersonalRecord:
                # Mock PersonalRecord queries - no existing records.
                query_mock.filter.return_value.all.return_value = []

            return query_mock

        mock_session.query.side_effect = mock_query_side_effect

        # Set processor user_id.
        processor.user_id = "123456789"

        # Act.
        processor._process_personal_records(pr_file, mock_session)

        # Assert - All 4 records should be processed.
        assert mock_upsert.called
        call_args = mock_upsert.call_args[1]
        model_instances = call_args["model_instances"]
        assert len(model_instances) == 4

        # Check activity-based record (typeId 3).
        activity_record = next(r for r in model_instances if r.type_id == 3)
        assert activity_record.activity_id == 12345
        assert activity_record.label == "Run: 5 km"

        # Check steps records (typeId 12, 13, 16) have NULL activity_id.
        steps_daily_record = next(r for r in model_instances if r.type_id == 12)
        assert steps_daily_record.activity_id is None
        assert steps_daily_record.label == "Steps: Most in a Day"

        steps_weekly_record = next(r for r in model_instances if r.type_id == 13)
        assert steps_weekly_record.activity_id is None
        assert steps_weekly_record.label == "Steps: Most in a Week"

        steps_unknown_record = next(r for r in model_instances if r.type_id == 16)
        assert steps_unknown_record.activity_id is None
        assert steps_unknown_record.label == "Steps: Unknown Type"

        # Verify conflict_columns match new primary key.
        conflict_columns = call_args["conflict_columns"]
        expected_columns = ["user_id", "type_id", "timestamp"]
        assert conflict_columns == expected_columns

    # ==================================================================================
    # Race Predictions Processing Tests.
    # ==================================================================================

    @pytest.fixture
    def sample_race_predictions_data(self) -> Dict:
        """
        Sample race predictions data for testing.
        """

        return {
            "userId": 15007510,
            "fromCalendarDate": None,
            "toCalendarDate": None,
            "calendarDate": "2025-08-08",
            "time5K": 1146,
            "time10K": 2465,
            "timeHalfMarathon": 5663,
            "timeMarathon": 12644,
        }

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_race_predictions_file(
        self,
        mock_upsert,
        processor,
        mock_session,
        temp_dir,
        sample_race_predictions_data,
    ):
        """
        Test _process_race_predictions with complete race predictions data.
        """

        # Arrange.
        rp_file = temp_dir / "123456789_RACE_PREDICTIONS_2025-08-07T12:00:00Z.json"
        with open(rp_file, "w", encoding="utf-8") as f:
            json.dump(sample_race_predictions_data, f)

        user_id = 1
        processor.user_id = user_id

        # Mock the user_id query.
        mock_session.query.return_value.filter.return_value.scalar.return_value = (
            123456789
        )

        # Mock no existing latest records.
        joined_query = mock_session.query.return_value.join.return_value
        filtered_query = joined_query.filter.return_value
        filtered_query.all.return_value = []

        # Act.
        processor._process_race_predictions(rp_file, mock_session)

        # Assert.
        # Verify upsert_model_instances was called with insert-only logic.
        mock_upsert.assert_called_once()
        call_args = mock_upsert.call_args

        assert call_args[1]["session"] == mock_session
        assert call_args[1]["conflict_columns"] == ["user_id", "date"]
        assert call_args[1]["on_conflict_update"] is False

        model_instances = call_args[1]["model_instances"]
        assert len(model_instances) == 1
        race_prediction = model_instances[0]

        assert isinstance(race_prediction, RacePredictions)
        assert race_prediction.user_id == user_id
        assert race_prediction.date == "2025-08-08"
        assert race_prediction.time_5k == 1146
        assert race_prediction.time_10k == 2465
        assert race_prediction.time_half_marathon == 5663
        assert race_prediction.time_marathon == 12644
        assert race_prediction.latest is True

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_race_predictions_with_latest_logic(
        self, mock_upsert, processor, mock_session, temp_dir
    ):
        """
        Test _process_race_predictions with latest flag management.
        """

        # Arrange.
        sample_data = {
            "calendarDate": "2025-08-08",
            "time5K": 1200,
            "time10K": 2500,
        }

        rp_file = temp_dir / "123456789_RACE_PREDICTIONS_2025-08-07T12:00:00Z.json"
        with open(rp_file, "w", encoding="utf-8") as f:
            json.dump(sample_data, f)

        user_id = 1
        processor.user_id = user_id

        # Mock existing latest records.
        existing_record1 = MagicMock()
        existing_record1.latest = True
        existing_record2 = MagicMock()
        existing_record2.latest = True
        existing_records = [existing_record1, existing_record2]

        # Mock the query to return existing records.
        mock_query = MagicMock()
        mock_query.filter.return_value.all.return_value = existing_records
        mock_session.query.return_value = mock_query

        # Act.
        processor._process_race_predictions(rp_file, mock_session)

        # Assert.
        # Verify existing records were set to latest=False.
        assert existing_record1.latest is False
        assert existing_record2.latest is False

        # Verify new record is created with latest=True and insert-only logic is used.
        mock_upsert.assert_called_once()
        call_args = mock_upsert.call_args
        assert call_args[1]["on_conflict_update"] is False

        model_instances = call_args[1]["model_instances"]
        race_prediction = model_instances[0]
        assert race_prediction.latest is True

    def test_process_race_predictions_missing_calendar_date(
        self, processor, mock_session, temp_dir
    ):
        """
        Test _process_race_predictions with missing calendar date raises KeyError.
        """

        # Arrange.
        sample_data = {
            "time5K": 1200,
            "time10K": 2500,
        }

        rp_file = temp_dir / "123456789_RACE_PREDICTIONS_2025-08-07T12:00:00Z.json"
        with open(rp_file, "w", encoding="utf-8") as f:
            json.dump(sample_data, f)

        user_id = 1
        processor.user_id = user_id

        # Act & Assert.
        # Should raise KeyError for missing required calendar date.
        with pytest.raises(KeyError):
            processor._process_race_predictions(rp_file, mock_session)

    def test_process_race_predictions_file_routing(
        self, processor, mock_session, temp_dir
    ):
        """
        Test that RACE_PREDICTIONS files are routed correctly.
        """

        # Arrange.
        rp_file = temp_dir / "123456789_RACE_PREDICTIONS_2025-08-07T12:00:00Z.json"
        with open(rp_file, "w", encoding="utf-8") as f:
            json.dump({"calendarDate": "2025-08-08"}, f)

        file_set = FileSet(files={GARMIN_FILE_TYPES.RACE_PREDICTIONS: [rp_file]})

        # Act.
        with patch.object(
            processor, "_process_race_predictions"
        ) as mock_process_rp, patch.object(
            processor, "_ensure_user_exists", return_value=1
        ) as mock_ensure_user:
            processor.process_file_set(file_set, mock_session)

        # Assert.
        mock_process_rp.assert_called_once_with(rp_file, mock_session)
        mock_ensure_user.assert_called_once_with("123456789", mock_session)

    @patch("dags.pipelines.garmin.process.upsert_model_instances")
    def test_process_race_predictions_partial_data(
        self, mock_upsert, processor, mock_session, temp_dir
    ):
        """
        Test _process_race_predictions with partial race time data.
        """

        # Arrange.
        sample_data = {
            "calendarDate": "2025-08-08",
            "time5K": 1200,
            # Missing other race times.
        }

        rp_file = temp_dir / "123456789_RACE_PREDICTIONS_2025-08-07T12:00:00Z.json"
        with open(rp_file, "w", encoding="utf-8") as f:
            json.dump(sample_data, f)

        user_id = 1
        processor.user_id = user_id

        # Mock no existing records.
        mock_session.query.return_value.filter.return_value.scalar.return_value = (
            123456789
        )
        joined_query = mock_session.query.return_value.join.return_value
        filtered_query = joined_query.filter.return_value
        filtered_query.all.return_value = []

        # Act.
        processor._process_race_predictions(rp_file, mock_session)

        # Assert.
        # Verify upsert was called with insert-only logic and partial data is
        # handled correctly.
        mock_upsert.assert_called_once()
        call_args = mock_upsert.call_args
        assert call_args[1]["on_conflict_update"] is False

        model_instances = call_args[1]["model_instances"]
        race_prediction = model_instances[0]

        assert race_prediction.time_5k == 1200
        assert race_prediction.time_10k is None
        assert race_prediction.time_half_marathon is None
        assert race_prediction.time_marathon is None

    # FIT File Processing Tests.
    @pytest.fixture
    def mock_fit_frame(self):
        """
        Create mock FIT frame for testing.
        """

        frame = MagicMock()
        frame.frame_type = 4  # fitdecode.FIT_FRAME_DATA
        frame.name = "record"
        frame.fields = []
        return frame

    @pytest.fixture
    def mock_fit_field(self):
        """
        Create mock FIT field for testing.
        """

        field = MagicMock()
        field.name = "heart_rate"
        field.value = 150
        field.units = "bpm"
        return field

    def test_process_fit_file_success(self, processor, mock_session, temp_dir):
        """
        Test successful FIT file processing.
        """

        # Arrange.
        activity_id = 12345
        fit_file = (
            temp_dir / f"15007510_ACTIVITY_{activity_id}_2025-08-07T12:00:00Z.fit"
        )
        fit_file.write_bytes(b"dummy fit data")

        # Mock existing activity.
        mock_activity = MagicMock()
        mock_activity.activity_id = activity_id
        mock_activity.ts_data_available = False

        mock_session.query().filter().first.return_value = mock_activity

        # Mock FIT frame and fields.
        mock_timestamp_field = MagicMock()
        mock_timestamp_field.name = "timestamp"
        mock_timestamp_field.value = datetime(2025, 8, 7, 14, 30, tzinfo=timezone.utc)

        mock_hr_field = MagicMock()
        mock_hr_field.name = "heart_rate"
        mock_hr_field.value = 150
        mock_hr_field.units = "bpm"

        mock_frame = MagicMock()
        mock_frame.frame_type = 4  # FIT_FRAME_DATA
        mock_frame.name = "record"
        mock_frame.fields = [mock_timestamp_field, mock_hr_field]

        mock_fit_reader = MagicMock()
        mock_fit_reader.__enter__.return_value = [mock_frame]

        with patch("fitdecode.FitReader", return_value=mock_fit_reader):
            with patch("fitdecode.FIT_FRAME_DATA", 4):
                # Act.
                processor._process_fit_file(fit_file, mock_session)

        # Assert.
        mock_session.bulk_save_objects.assert_called_once()
        ts_metrics = mock_session.bulk_save_objects.call_args[0][0]
        assert len(ts_metrics) == 1
        assert ts_metrics[0].activity_id == activity_id
        assert ts_metrics[0].name == "heart_rate"
        assert ts_metrics[0].value == 150.0
        assert ts_metrics[0].units == "bpm"
        assert mock_activity.ts_data_available is True

    def test_process_fit_file_already_processed(
        self, processor, mock_session, temp_dir
    ):
        """
        Test FIT file processing when data already exists.
        """

        # Arrange.
        activity_id = 12345
        fit_file = (
            temp_dir / f"15007510_ACTIVITY_{activity_id}_2025-08-07T12:00:00Z.fit"
        )
        fit_file.write_bytes(b"dummy fit data")

        mock_activity = MagicMock()
        mock_activity.activity_id = activity_id
        mock_activity.ts_data_available = True
        mock_session.query().filter().first.return_value = mock_activity

        # Act.
        processor._process_fit_file(fit_file, mock_session)

        # Assert - no processing should occur since ts_data_available is True.
        mock_session.bulk_save_objects.assert_not_called()

    def test_process_fit_file_activity_not_found(
        self, processor, mock_session, temp_dir
    ):
        """
        Test FIT file processing when activity doesn't exist.
        """

        # Arrange.
        activity_id = 12345
        fit_file = (
            temp_dir / f"15007510_ACTIVITY_{activity_id}_2025-08-07T12:00:00Z.fit"
        )
        fit_file.write_bytes(b"dummy fit data")

        mock_session.query().filter().first.return_value = None

        # Act & Assert.
        with pytest.raises(ValueError, match="Activity 12345 not found in database"):
            processor._process_fit_file(fit_file, mock_session)

    def test_process_fit_file_invalid_filename(self, processor, mock_session, temp_dir):
        """
        Test FIT file processing with invalid filename.
        """

        # Arrange.
        fit_file = temp_dir / "invalid_filename.fit"
        fit_file.write_bytes(b"dummy fit data")

        # Act & Assert.
        with pytest.raises(
            ValueError, match="Cannot extract activity_id from filename"
        ):
            processor._process_fit_file(fit_file, mock_session)

    def test_process_fit_file_filters_unknown_fields(
        self, processor, mock_session, temp_dir
    ):
        """
        Test that FIT file processing filters out UNKNOWN fields.
        """

        # Arrange.
        activity_id = 12345
        fit_file = (
            temp_dir / f"15007510_ACTIVITY_{activity_id}_2025-08-07T12:00:00Z.fit"
        )
        fit_file.write_bytes(b"dummy fit data")

        mock_activity = MagicMock()
        mock_activity.activity_id = activity_id
        mock_activity.ts_data_available = False
        mock_session.query().filter().first.return_value = mock_activity

        # Mock fields with one UNKNOWN field.
        mock_timestamp_field = MagicMock()
        mock_timestamp_field.name = "timestamp"
        mock_timestamp_field.value = datetime(2025, 8, 7, 14, 30, tzinfo=timezone.utc)

        mock_valid_field = MagicMock()
        mock_valid_field.name = "heart_rate"
        mock_valid_field.value = 150
        mock_valid_field.units = "bpm"

        mock_unknown_field = MagicMock()
        mock_unknown_field.name = "unknown_field"
        mock_unknown_field.value = 999
        mock_unknown_field.units = "unknown"

        mock_frame = MagicMock()
        mock_frame.frame_type = 4  # FIT_FRAME_DATA
        mock_frame.name = "record"
        mock_frame.fields = [mock_timestamp_field, mock_valid_field, mock_unknown_field]

        mock_fit_reader = MagicMock()
        mock_fit_reader.__enter__.return_value = [mock_frame]

        with patch("fitdecode.FitReader", return_value=mock_fit_reader):
            with patch("fitdecode.FIT_FRAME_DATA", 4):
                # Act.
                processor._process_fit_file(fit_file, mock_session)

        # Assert - only valid field should be processed.
        mock_session.bulk_save_objects.assert_called_once()
        ts_metrics = mock_session.bulk_save_objects.call_args[0][0]
        assert len(ts_metrics) == 1
        assert ts_metrics[0].name == "heart_rate"

    def test_process_fit_file_handles_fit_decode_error(
        self, processor, mock_session, temp_dir
    ):
        """
        Test FIT file processing raises fitdecode errors.
        """

        # Arrange.
        activity_id = 12345
        fit_file = (
            temp_dir / f"15007510_ACTIVITY_{activity_id}_2025-08-07T12:00:00Z.fit"
        )
        fit_file.write_bytes(b"dummy fit data")

        mock_activity = MagicMock()
        mock_activity.activity_id = activity_id
        mock_activity.ts_data_available = False
        mock_session.query().filter().first.return_value = mock_activity

        with patch("fitdecode.FitReader", side_effect=Exception("FIT decode error")):
            # Act & Assert.
            with pytest.raises(Exception, match="FIT decode error"):
                processor._process_fit_file(fit_file, mock_session)

    def test_process_file_set_handles_fit_files_after_json(
        self, processor, mock_session, temp_dir
    ):
        """
        Test that process_file_set handles FIT files after JSON files.
        """

        # Arrange.
        json_file = temp_dir / "15007510_USER_PROFILE_2025-08-07T12:00:00Z.json"
        json_file.write_text(
            json.dumps({"userData": {"gender": "MALE"}, "full_name": "Test User"})
        )

        fit_file = temp_dir / "15007510_ACTIVITY_12345_2025-08-07T12:00:00Z.fit"
        fit_file.write_bytes(b"dummy fit data")

        # Create a file set with JSON and FIT files.
        file_set = FileSet(
            files={
                GARMIN_FILE_TYPES.USER_PROFILE: [json_file],
                GARMIN_FILE_TYPES.ACTIVITY: [fit_file],
            }
        )

        # Mock existing activity.
        mock_activity = MagicMock()
        mock_activity.activity_id = 12345
        mock_activity.ts_data_available = False
        mock_session.query().filter().first.return_value = mock_activity

        # Mock FIT processing.
        with patch.object(processor, "_process_fit_file") as mock_process_fit:
            # Act.
            processor.process_file_set(file_set, mock_session)

        # Assert - FIT file processing was called.
        mock_process_fit.assert_called_once_with(fit_file, mock_session)

    def test_process_fit_file_lap_processing(self, processor, mock_session, temp_dir):
        """
        Test FIT file processing with lap frames.
        """

        # Arrange.
        activity_id = 12345
        fit_file = (
            temp_dir / f"15007510_ACTIVITY_{activity_id}_2025-08-07T12:00:00Z.fit"
        )
        fit_file.write_bytes(b"dummy fit data")

        # Mock existing activity.
        mock_activity = MagicMock()
        mock_activity.activity_id = activity_id
        mock_activity.ts_data_available = False
        mock_session.query().filter().first.return_value = mock_activity

        # Mock FIT lap frame and fields.
        mock_total_distance_field = MagicMock()
        mock_total_distance_field.name = "total_distance"
        mock_total_distance_field.value = 1000.5
        mock_total_distance_field.units = "m"

        mock_total_elapsed_time_field = MagicMock()
        mock_total_elapsed_time_field.name = "total_elapsed_time"
        mock_total_elapsed_time_field.value = 300.0
        mock_total_elapsed_time_field.units = "s"

        mock_unknown_field = MagicMock()
        mock_unknown_field.name = "unknown_123"
        mock_unknown_field.value = 456
        mock_unknown_field.units = None

        mock_lap_frame = MagicMock()
        mock_lap_frame.frame_type = 4  # FIT_FRAME_DATA
        mock_lap_frame.name = "lap"
        mock_lap_frame.fields = [
            mock_total_distance_field,
            mock_total_elapsed_time_field,
            mock_unknown_field,
        ]

        mock_fit_reader = MagicMock()
        mock_fit_reader.__enter__.return_value = [mock_lap_frame]

        with patch("fitdecode.FitReader", return_value=mock_fit_reader):
            with patch("fitdecode.FIT_FRAME_DATA", 4):
                # Act.
                processor._process_fit_file(fit_file, mock_session)

        # Assert.
        mock_session.bulk_save_objects.assert_called_once()
        lap_metrics = mock_session.bulk_save_objects.call_args[0][0]

        assert len(lap_metrics) == 2

        # Verify lap metrics.
        lap_metric_1 = lap_metrics[0]
        assert lap_metric_1.activity_id == activity_id
        assert lap_metric_1.lap_idx == 1
        assert lap_metric_1.name == "total_distance"
        assert lap_metric_1.value == 1000.5
        assert lap_metric_1.units == "m"

        lap_metric_2 = lap_metrics[1]
        assert lap_metric_2.activity_id == activity_id
        assert lap_metric_2.lap_idx == 1
        assert lap_metric_2.name == "total_elapsed_time"
        assert lap_metric_2.value == 300.0
        assert lap_metric_2.units == "s"

    def test_process_fit_file_split_processing(self, processor, mock_session, temp_dir):
        """
        Test FIT file processing with split frames.
        """

        # Arrange.
        activity_id = 12345
        fit_file = (
            temp_dir / f"15007510_ACTIVITY_{activity_id}_2025-08-07T12:00:00Z.fit"
        )
        fit_file.write_bytes(b"dummy fit data")

        # Mock existing activity.
        mock_activity = MagicMock()
        mock_activity.activity_id = activity_id
        mock_activity.ts_data_available = False
        mock_session.query().filter().first.return_value = mock_activity

        # Mock FIT split frame and fields.
        mock_split_type_field = MagicMock()
        mock_split_type_field.name = "split_type"
        mock_split_type_field.value = "rwd_run"
        mock_split_type_field.units = None

        mock_total_distance_field = MagicMock()
        mock_total_distance_field.name = "total_distance"
        mock_total_distance_field.value = 500.0
        mock_total_distance_field.units = "m"

        mock_avg_speed_field = MagicMock()
        mock_avg_speed_field.name = "avg_speed"
        mock_avg_speed_field.value = 2.5
        mock_avg_speed_field.units = "m/s"

        mock_null_field = MagicMock()
        mock_null_field.name = "null_field"
        mock_null_field.value = None
        mock_null_field.units = None

        mock_split_frame = MagicMock()
        mock_split_frame.frame_type = 4  # FIT_FRAME_DATA
        mock_split_frame.name = "split"
        mock_split_frame.fields = [
            mock_split_type_field,
            mock_total_distance_field,
            mock_avg_speed_field,
            mock_null_field,
        ]

        mock_fit_reader = MagicMock()
        mock_fit_reader.__enter__.return_value = [mock_split_frame]

        with patch("fitdecode.FitReader", return_value=mock_fit_reader):
            with patch("fitdecode.FIT_FRAME_DATA", 4):
                # Act.
                processor._process_fit_file(fit_file, mock_session)

        # Assert.
        mock_session.bulk_save_objects.assert_called_once()
        split_metrics = mock_session.bulk_save_objects.call_args[0][0]

        assert len(split_metrics) == 2

        # Verify split metrics.
        split_metric_1 = split_metrics[0]
        assert split_metric_1.activity_id == activity_id
        assert split_metric_1.split_idx == 1
        assert split_metric_1.split_type == "rwd_run"
        assert split_metric_1.name == "total_distance"
        assert split_metric_1.value == 500.0
        assert split_metric_1.units == "m"

        split_metric_2 = split_metrics[1]
        assert split_metric_2.activity_id == activity_id
        assert split_metric_2.split_idx == 1
        assert split_metric_2.split_type == "rwd_run"
        assert split_metric_2.name == "avg_speed"
        assert split_metric_2.value == 2.5
        assert split_metric_2.units == "m/s"

    def test_process_fit_file_lap_array_field_handling(
        self, processor, mock_session, temp_dir
    ):
        """
        Test FIT file processing with lap frames containing array fields.
        """

        # Arrange.
        activity_id = 12345
        fit_file = (
            temp_dir / f"15007510_ACTIVITY_{activity_id}_2025-08-07T12:00:00Z.fit"
        )
        fit_file.write_bytes(b"dummy fit data")

        # Mock existing activity.
        mock_activity = MagicMock()
        mock_activity.activity_id = activity_id
        mock_activity.ts_data_available = False
        mock_session.query().filter().first.return_value = mock_activity

        # Mock FIT lap frame with array field.
        mock_array_field = MagicMock()
        mock_array_field.name = "heart_rate_zones"
        mock_array_field.value = [120, 140, 160]
        mock_array_field.units = "bpm"

        mock_regular_field = MagicMock()
        mock_regular_field.name = "avg_heart_rate"
        mock_regular_field.value = 145
        mock_regular_field.units = "bpm"

        mock_lap_frame = MagicMock()
        mock_lap_frame.frame_type = 4  # FIT_FRAME_DATA
        mock_lap_frame.name = "lap"
        mock_lap_frame.fields = [mock_array_field, mock_regular_field]

        mock_fit_reader = MagicMock()
        mock_fit_reader.__enter__.return_value = [mock_lap_frame]

        with patch("fitdecode.FitReader", return_value=mock_fit_reader):
            with patch("fitdecode.FIT_FRAME_DATA", 4):
                # Act.
                processor._process_fit_file(fit_file, mock_session)

        # Assert.
        mock_session.bulk_save_objects.assert_called_once()
        lap_metrics = mock_session.bulk_save_objects.call_args[0][0]

        assert len(lap_metrics) == 4  # 3 array elements + 1 regular field

        # Verify array field handling with suffix indexing.
        expected_names = [
            "heart_rate_zones_1",
            "heart_rate_zones_2",
            "heart_rate_zones_3",
            "avg_heart_rate",
        ]
        expected_values = [120.0, 140.0, 160.0, 145.0]

        for i, lap_metric in enumerate(lap_metrics):
            assert lap_metric.activity_id == activity_id
            assert lap_metric.lap_idx == 1
            assert lap_metric.name == expected_names[i]
            assert lap_metric.value == expected_values[i]
            assert lap_metric.units == "bpm"

    def test_process_fit_file_split_array_field_handling(
        self, processor, mock_session, temp_dir
    ):
        """
        Test FIT file processing with split frames containing array fields.
        """

        # Arrange.
        activity_id = 12345
        fit_file = (
            temp_dir / f"15007510_ACTIVITY_{activity_id}_2025-08-07T12:00:00Z.fit"
        )
        fit_file.write_bytes(b"dummy fit data")

        # Mock existing activity.
        mock_activity = MagicMock()
        mock_activity.activity_id = activity_id
        mock_activity.ts_data_available = False
        mock_session.query().filter().first.return_value = mock_activity

        # Mock FIT split frame with array field.
        mock_split_type_field = MagicMock()
        mock_split_type_field.name = "split_type"
        mock_split_type_field.value = "interval_active"
        mock_split_type_field.units = None

        mock_array_field = MagicMock()
        mock_array_field.name = "speed_zones"
        mock_array_field.value = [1.5, 2.0, 2.5]
        mock_array_field.units = "m/s"

        mock_split_frame = MagicMock()
        mock_split_frame.frame_type = 4  # FIT_FRAME_DATA
        mock_split_frame.name = "split"
        mock_split_frame.fields = [mock_split_type_field, mock_array_field]

        mock_fit_reader = MagicMock()
        mock_fit_reader.__enter__.return_value = [mock_split_frame]

        with patch("fitdecode.FitReader", return_value=mock_fit_reader):
            with patch("fitdecode.FIT_FRAME_DATA", 4):
                # Act.
                processor._process_fit_file(fit_file, mock_session)

        # Assert.
        mock_session.bulk_save_objects.assert_called_once()
        split_metrics = mock_session.bulk_save_objects.call_args[0][0]

        assert len(split_metrics) == 3  # 3 array elements

        # Verify array field handling with suffix indexing.
        expected_names = ["speed_zones_1", "speed_zones_2", "speed_zones_3"]
        expected_values = [1.5, 2.0, 2.5]

        for i, split_metric in enumerate(split_metrics):
            assert split_metric.activity_id == activity_id
            assert split_metric.split_idx == 1
            assert split_metric.split_type == "interval_active"
            assert split_metric.name == expected_names[i]
            assert split_metric.value == expected_values[i]
            assert split_metric.units == "m/s"

    def test_process_fit_file_multiple_laps_and_splits(
        self, processor, mock_session, temp_dir
    ):
        """
        Test FIT file processing with multiple lap and split frames.
        """

        # Arrange.
        activity_id = 12345
        fit_file = (
            temp_dir / f"15007510_ACTIVITY_{activity_id}_2025-08-07T12:00:00Z.fit"
        )
        fit_file.write_bytes(b"dummy fit data")

        # Mock existing activity.
        mock_activity = MagicMock()
        mock_activity.activity_id = activity_id
        mock_activity.ts_data_available = False
        mock_session.query().filter().first.return_value = mock_activity

        # Mock first lap frame.
        mock_lap1_field = MagicMock()
        mock_lap1_field.name = "total_distance"
        mock_lap1_field.value = 1000.0
        mock_lap1_field.units = "m"

        mock_lap1_frame = MagicMock()
        mock_lap1_frame.frame_type = 4  # FIT_FRAME_DATA
        mock_lap1_frame.name = "lap"
        mock_lap1_frame.fields = [mock_lap1_field]

        # Mock second lap frame.
        mock_lap2_field = MagicMock()
        mock_lap2_field.name = "total_distance"
        mock_lap2_field.value = 2000.0
        mock_lap2_field.units = "m"

        mock_lap2_frame = MagicMock()
        mock_lap2_frame.frame_type = 4  # FIT_FRAME_DATA
        mock_lap2_frame.name = "lap"
        mock_lap2_frame.fields = [mock_lap2_field]

        # Mock first split frame.
        mock_split1_type_field = MagicMock()
        mock_split1_type_field.name = "split_type"
        mock_split1_type_field.value = "rwd_run"
        mock_split1_type_field.units = None

        mock_split1_field = MagicMock()
        mock_split1_field.name = "avg_speed"
        mock_split1_field.value = 2.5
        mock_split1_field.units = "m/s"

        mock_split1_frame = MagicMock()
        mock_split1_frame.frame_type = 4  # FIT_FRAME_DATA
        mock_split1_frame.name = "split"
        mock_split1_frame.fields = [mock_split1_type_field, mock_split1_field]

        # Mock second split frame.
        mock_split2_type_field = MagicMock()
        mock_split2_type_field.name = "split_type"
        mock_split2_type_field.value = "rwd_walk"
        mock_split2_type_field.units = None

        mock_split2_field = MagicMock()
        mock_split2_field.name = "avg_speed"
        mock_split2_field.value = 1.5
        mock_split2_field.units = "m/s"

        mock_split2_frame = MagicMock()
        mock_split2_frame.frame_type = 4  # FIT_FRAME_DATA
        mock_split2_frame.name = "split"
        mock_split2_frame.fields = [mock_split2_type_field, mock_split2_field]

        mock_fit_reader = MagicMock()
        mock_fit_reader.__enter__.return_value = [
            mock_lap1_frame,
            mock_split1_frame,
            mock_lap2_frame,
            mock_split2_frame,
        ]

        with patch("fitdecode.FitReader", return_value=mock_fit_reader):
            with patch("fitdecode.FIT_FRAME_DATA", 4):
                # Act.
                processor._process_fit_file(fit_file, mock_session)

        # Assert.
        assert mock_session.bulk_save_objects.call_count == 2
        calls = mock_session.bulk_save_objects.call_args_list

        # Check that split_metrics and lap_metrics were saved.
        split_metrics = calls[0][0][0]
        lap_metrics = calls[1][0][0]

        assert len(split_metrics) == 2
        assert len(lap_metrics) == 2

        # Verify split metrics with correct indices.
        split_metric_1 = split_metrics[0]
        assert split_metric_1.activity_id == activity_id
        assert split_metric_1.split_idx == 1
        assert split_metric_1.split_type == "rwd_run"
        assert split_metric_1.name == "avg_speed"
        assert split_metric_1.value == 2.5

        split_metric_2 = split_metrics[1]
        assert split_metric_2.activity_id == activity_id
        assert split_metric_2.split_idx == 2
        assert split_metric_2.split_type == "rwd_walk"
        assert split_metric_2.name == "avg_speed"
        assert split_metric_2.value == 1.5

        # Verify lap metrics with correct indices.
        lap_metric_1 = lap_metrics[0]
        assert lap_metric_1.activity_id == activity_id
        assert lap_metric_1.lap_idx == 1
        assert lap_metric_1.name == "total_distance"
        assert lap_metric_1.value == 1000.0

        lap_metric_2 = lap_metrics[1]
        assert lap_metric_2.activity_id == activity_id
        assert lap_metric_2.lap_idx == 2
        assert lap_metric_2.name == "total_distance"
        assert lap_metric_2.value == 2000.0

    def test_process_fit_file_lap_split_error_handling(
        self, processor, mock_session, temp_dir
    ):
        """
        Test FIT file processing error handling for lap and split frames.
        """

        # Arrange.
        activity_id = 12345
        fit_file = (
            temp_dir / f"15007510_ACTIVITY_{activity_id}_2025-08-07T12:00:00Z.fit"
        )
        fit_file.write_bytes(b"dummy fit data")

        # Mock existing activity.
        mock_activity = MagicMock()
        mock_activity.activity_id = activity_id
        mock_activity.ts_data_available = False
        mock_session.query().filter().first.return_value = mock_activity

        # Mock lap frame with unconvertible value.
        mock_invalid_field = MagicMock()
        mock_invalid_field.name = "invalid_field"
        mock_invalid_field.value = "not_a_number"
        mock_invalid_field.units = "units"

        mock_valid_field = MagicMock()
        mock_valid_field.name = "valid_field"
        mock_valid_field.value = 123.45
        mock_valid_field.units = "units"

        mock_lap_frame = MagicMock()
        mock_lap_frame.frame_type = 4  # FIT_FRAME_DATA
        mock_lap_frame.name = "lap"
        mock_lap_frame.fields = [mock_invalid_field, mock_valid_field]

        mock_fit_reader = MagicMock()
        mock_fit_reader.__enter__.return_value = [mock_lap_frame]

        with patch("fitdecode.FitReader", return_value=mock_fit_reader):
            with patch("fitdecode.FIT_FRAME_DATA", 4):
                # Act.
                processor._process_fit_file(fit_file, mock_session)

        # Assert - should skip invalid field but process valid one.
        mock_session.bulk_save_objects.assert_called_once()
        lap_metrics = mock_session.bulk_save_objects.call_args[0][0]

        assert len(lap_metrics) == 1

        # Verify only the valid field was processed.
        lap_metric = lap_metrics[0]
        assert lap_metric.activity_id == activity_id
        assert lap_metric.lap_idx == 1
        assert lap_metric.name == "valid_field"
        assert lap_metric.value == 123.45
        assert lap_metric.units == "units"
