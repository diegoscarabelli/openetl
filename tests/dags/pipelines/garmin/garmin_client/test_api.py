"""
Unit tests for dags.pipelines.garmin.garmin_client.api module.

Verifies the URL patterns, query parameters, and pagination behavior of the 15 API
method wrappers used by the openetl pipeline. Each test mocks ``client._connectapi`` (or
``_download``) and asserts the correct URL/params were passed.
"""

from unittest.mock import MagicMock

import pytest

from dags.pipelines.garmin.garmin_client import api
from dags.pipelines.garmin.garmin_client.api import (
    ActivityDownloadFormat,
    _validate_date_format,
)


@pytest.fixture
def mock_client() -> MagicMock:
    """
    Build a mock GarminClient with a stub display_name.

    :return: MagicMock standing in for a GarminClient instance.
    """
    client = MagicMock()
    client.display_name = "stub_user"
    return client


# ----------------------------------------------------------------------------------------
# DATE VALIDATION
# ----------------------------------------------------------------------------------------


class TestValidateDateFormat:
    """
    Tests for ``_validate_date_format``.
    """

    def test_accepts_well_formed_date(self) -> None:
        """
        A YYYY-MM-DD string passes through unchanged.
        """
        assert _validate_date_format("2026-04-07") == "2026-04-07"

    def test_strips_whitespace(self) -> None:
        """
        Surrounding whitespace is stripped.
        """
        assert _validate_date_format("  2026-04-07  ") == "2026-04-07"

    def test_rejects_wrong_shape(self) -> None:
        """
        Strings that don't match YYYY-MM-DD raise ValueError.
        """
        with pytest.raises(ValueError):
            _validate_date_format("04/07/2026")

    def test_rejects_invalid_calendar_date(self) -> None:
        """
        Strings with the right shape but an invalid date raise ValueError.
        """
        with pytest.raises(ValueError):
            _validate_date_format("2026-02-30")

    def test_rejects_non_string(self) -> None:
        """
        Non-string inputs raise ValueError.
        """
        with pytest.raises(ValueError):
            _validate_date_format(20260407)  # type: ignore[arg-type]


# ----------------------------------------------------------------------------------------
# DAILY WELLNESS METHODS (need display_name interpolation)
# ----------------------------------------------------------------------------------------


class TestGetSleepData:
    """
    Tests for ``get_sleep_data``.
    """

    def test_calls_correct_url_with_buffer_param(self, mock_client: MagicMock) -> None:
        """
        Sleep URL contains the display name and the request includes the
        ``nonSleepBufferMinutes=60`` query param.
        """
        # Arrange.
        mock_client._connectapi.return_value = {"sleep": "data"}

        # Act.
        result = api.get_sleep_data(mock_client, "2026-04-07")

        # Assert.
        assert result == {"sleep": "data"}
        url = mock_client._connectapi.call_args[0][0]
        params = mock_client._connectapi.call_args[1]["params"]
        assert url == "/wellness-service/wellness/dailySleepData/stub_user"
        assert params == {"date": "2026-04-07", "nonSleepBufferMinutes": 60}


class TestGetStressData:
    """
    Tests for ``get_stress_data``.
    """

    def test_calls_correct_url(self, mock_client: MagicMock) -> None:
        """
        Stress URL embeds the date in the path (no display_name).
        """
        # Arrange.
        mock_client._connectapi.return_value = {"stress": "data"}

        # Act.
        result = api.get_stress_data(mock_client, "2026-04-07")

        # Assert.
        assert result == {"stress": "data"}
        url = mock_client._connectapi.call_args[0][0]
        assert url == "/wellness-service/wellness/dailyStress/2026-04-07"


class TestGetRespirationData:
    """
    Tests for ``get_respiration_data``.
    """

    def test_calls_correct_url(self, mock_client: MagicMock) -> None:
        """
        Respiration URL embeds the date in the path.
        """
        # Arrange.
        mock_client._connectapi.return_value = {"resp": "data"}

        # Act.
        result = api.get_respiration_data(mock_client, "2026-04-07")

        # Assert.
        assert result == {"resp": "data"}
        url = mock_client._connectapi.call_args[0][0]
        assert url == "/wellness-service/wellness/daily/respiration/2026-04-07"


class TestGetHeartRates:
    """
    Tests for ``get_heart_rates``.
    """

    def test_calls_correct_url_with_date_param(self, mock_client: MagicMock) -> None:
        """
        Heart rate URL contains display_name and a ``date`` query param.
        """
        # Arrange.
        mock_client._connectapi.return_value = {"hr": "data"}

        # Act.
        api.get_heart_rates(mock_client, "2026-04-07")

        # Assert.
        url = mock_client._connectapi.call_args[0][0]
        params = mock_client._connectapi.call_args[1]["params"]
        assert url == "/wellness-service/wellness/dailyHeartRate/stub_user"
        assert params == {"date": "2026-04-07"}


class TestGetTrainingReadiness:
    """
    Tests for ``get_training_readiness``.
    """

    def test_calls_correct_url(self, mock_client: MagicMock) -> None:
        """
        Training readiness URL embeds the date in the path.
        """
        # Arrange.
        mock_client._connectapi.return_value = [{"score": 80}]

        # Act.
        api.get_training_readiness(mock_client, "2026-04-07")

        # Assert.
        url = mock_client._connectapi.call_args[0][0]
        assert url == "/metrics-service/metrics/trainingreadiness/2026-04-07"


class TestGetTrainingStatus:
    """
    Tests for ``get_training_status``.
    """

    def test_calls_correct_url(self, mock_client: MagicMock) -> None:
        """
        Training status URL embeds the date in the path.
        """
        # Arrange.
        mock_client._connectapi.return_value = {"status": "productive"}

        # Act.
        api.get_training_status(mock_client, "2026-04-07")

        # Assert.
        url = mock_client._connectapi.call_args[0][0]
        assert url == "/metrics-service/metrics/trainingstatus/aggregated/2026-04-07"


class TestGetStepsData:
    """
    Tests for ``get_steps_data``.
    """

    def test_calls_correct_url_with_date_param(self, mock_client: MagicMock) -> None:
        """
        Steps URL contains display_name and a ``date`` query param.
        """
        # Arrange.
        mock_client._connectapi.return_value = [{"steps": 100}]

        # Act.
        result = api.get_steps_data(mock_client, "2026-04-07")

        # Assert.
        assert result == [{"steps": 100}]
        url = mock_client._connectapi.call_args[0][0]
        params = mock_client._connectapi.call_args[1]["params"]
        assert url == "/wellness-service/wellness/dailySummaryChart/stub_user"
        assert params == {"date": "2026-04-07"}

    def test_returns_empty_list_when_response_none(
        self, mock_client: MagicMock
    ) -> None:
        """
        A None response is normalized to an empty list.
        """
        # Arrange.
        mock_client._connectapi.return_value = None
        # Act.
        result = api.get_steps_data(mock_client, "2026-04-07")

        # Assert.
        assert result == []


class TestGetFloors:
    """
    Tests for ``get_floors``.
    """

    def test_calls_correct_url(self, mock_client: MagicMock) -> None:
        """
        Floors URL embeds the date in the path.
        """
        # Act.
        api.get_floors(mock_client, "2026-04-07")
        # Assert.
        url = mock_client._connectapi.call_args[0][0]
        assert url == "/wellness-service/wellness/floorsChartData/daily/2026-04-07"


class TestGetIntensityMinutesData:
    """
    Tests for ``get_intensity_minutes_data``.
    """

    def test_calls_correct_url(self, mock_client: MagicMock) -> None:
        """
        Intensity minutes URL embeds the date in the path.
        """
        # Act.
        api.get_intensity_minutes_data(mock_client, "2026-04-07")
        # Assert.
        url = mock_client._connectapi.call_args[0][0]
        assert url == "/wellness-service/wellness/daily/im/2026-04-07"


class TestGetBodyComposition:
    """
    Tests for ``get_body_composition`` endpoint, params, and empty-response
    normalization.

    Uses the ``weight/range/{start}/{end}?includeAll=true`` endpoint, which returns
    every weigh-in grouped under ``dailyWeightSummaries[].allWeightMetrics`` (the older
    ``daterangesnapshot`` endpoint returned only one representative weigh-in per day,
    silently dropping the rest). On no-data windows the endpoint returns a wrapper dict
    with an empty ``dailyWeightSummaries``; ``get_body_composition`` must collapse that
    to ``None`` so the extractor short-circuits the file write.
    """

    def test_returns_payload_when_weighins_present(
        self, mock_client: MagicMock
    ) -> None:
        """
        A populated ``dailyWeightSummaries`` must be returned verbatim so the extractor
        saves the file and the splitter can group weigh-ins per day downstream.
        """
        payload = {
            "dailyWeightSummaries": [
                {
                    "summaryDate": "2026-04-15",
                    "allWeightMetrics": [
                        {
                            "timestampGMT": 1713182400000,
                            "weight": 75300.0,
                            "bmi": 24.5,
                            "sourceType": "INDEX_SCALE",
                        }
                    ],
                }
            ],
        }
        mock_client._connectapi.return_value = payload

        result = api.get_body_composition(mock_client, "2026-04-15")

        assert result is payload
        mock_client._connectapi.assert_called_once_with(
            "/weight-service/weight/range/2026-04-15/2026-04-15",
            params={"includeAll": "true"},
        )

    def test_returns_none_when_daily_summaries_empty(
        self, mock_client: MagicMock
    ) -> None:
        """
        On no-data windows the API returns the wrapper dict with an empty
        ``dailyWeightSummaries``.

        ``get_body_composition`` must collapse that to ``None`` so the extractor's
        truthiness check skips the file write.
        """
        mock_client._connectapi.return_value = {
            "dailyWeightSummaries": [],
            "totalAverage": {"weight": None, "bmi": None},
        }

        result = api.get_body_composition(mock_client, "2026-04-15")

        assert result is None

    def test_returns_none_when_daily_summaries_missing(
        self, mock_client: MagicMock
    ) -> None:
        """
        Defensive: if the endpoint ever omits ``dailyWeightSummaries`` entirely, treat
        that as no data rather than letting a wrapper-only dict through.
        """
        mock_client._connectapi.return_value = {
            "startDate": "2026-04-15",
            "endDate": "2026-04-15",
        }

        result = api.get_body_composition(mock_client, "2026-04-15")

        assert result is None

    def test_returns_none_when_response_is_none(self, mock_client: MagicMock) -> None:
        """
        If ``_connectapi`` returns ``None`` (e.g. transient empty body), pass that
        through as ``None`` rather than raising.
        """
        mock_client._connectapi.return_value = None

        result = api.get_body_composition(mock_client, "2026-04-15")

        assert result is None

    def test_default_enddate_matches_startdate(self, mock_client: MagicMock) -> None:
        """
        When ``enddate`` is omitted, ``startdate`` is used for both path bounds (single-
        day query), matching the day-stamped file the splitter writes.
        """
        mock_client._connectapi.return_value = {"dailyWeightSummaries": []}

        api.get_body_composition(mock_client, "2026-04-15")

        mock_client._connectapi.assert_called_once_with(
            "/weight-service/weight/range/2026-04-15/2026-04-15",
            params={"includeAll": "true"},
        )

    def test_distinct_start_and_end_dates_in_path(self, mock_client: MagicMock) -> None:
        """
        A multi-day window puts both bounds in the URL path: the endpoint takes the
        range natively (the extractor issues one call per window, not per day).
        """
        mock_client._connectapi.return_value = {"dailyWeightSummaries": []}

        api.get_body_composition(mock_client, "2026-04-15", "2026-04-20")

        mock_client._connectapi.assert_called_once_with(
            "/weight-service/weight/range/2026-04-15/2026-04-20",
            params={"includeAll": "true"},
        )


# ----------------------------------------------------------------------------------------
# RUNNING TOLERANCE
# ----------------------------------------------------------------------------------------


class TestGetRunningTolerance:
    """
    Tests for ``get_running_tolerance``.

    Running tolerance is Garmin's biomechanical running-load model. The stats endpoint
    with ``aggregation=daily`` returns one object per calendar day; accounts without a
    compatible watch get an empty response, which is normalized to ``None`` so the
    extractor skips the file write.
    """

    def test_calls_stats_url_with_range_and_aggregation_params(
        self, mock_client: MagicMock
    ) -> None:
        """
        The stats endpoint receives ``startDate``, ``endDate``, and
        ``aggregation=daily`` as query params, and the daily list is returned verbatim.
        """
        payload = [
            {"calendarDate": "2026-04-15", "totalImpactLoad": 1200, "tolerance": 1500}
        ]
        mock_client._connectapi.return_value = payload

        result = api.get_running_tolerance(mock_client, "2026-04-15", "2026-04-20")

        assert result is payload
        mock_client._connectapi.assert_called_once_with(
            "/metrics-service/metrics/runningtolerance/stats",
            params={
                "startDate": "2026-04-15",
                "endDate": "2026-04-20",
                "aggregation": "daily",
            },
        )

    def test_default_enddate_matches_startdate(self, mock_client: MagicMock) -> None:
        """
        When ``enddate`` is omitted, ``startdate`` is used for both bounds.
        """
        mock_client._connectapi.return_value = [{"calendarDate": "2026-04-15"}]

        api.get_running_tolerance(mock_client, "2026-04-15")

        params = mock_client._connectapi.call_args[1]["params"]
        assert params["startDate"] == "2026-04-15"
        assert params["endDate"] == "2026-04-15"
        assert params["aggregation"] == "daily"

    def test_returns_none_when_empty(self, mock_client: MagicMock) -> None:
        """
        An empty list (account without a compatible watch) is normalized to ``None`` so
        the extractor's truthiness check skips the file write.
        """
        mock_client._connectapi.return_value = []

        result = api.get_running_tolerance(mock_client, "2026-04-15")

        assert result is None

    def test_returns_none_when_response_is_none(self, mock_client: MagicMock) -> None:
        """
        A ``None`` response passes through as ``None`` rather than raising.
        """
        mock_client._connectapi.return_value = None

        result = api.get_running_tolerance(mock_client, "2026-04-15")

        assert result is None


# ----------------------------------------------------------------------------------------
# MENSTRUAL CYCLE
# ----------------------------------------------------------------------------------------


class TestGetMenstrualDataForDate:
    """
    Tests for ``get_menstrual_data_for_date`` (dayview endpoint).
    """

    def test_returns_payload_when_day_summary_or_log_present(
        self, mock_client: MagicMock
    ) -> None:
        """
        A dict response with a populated ``daySummary`` or ``dayLog`` must be returned
        verbatim so the processor can extract fields.
        """
        mock_client._connectapi.return_value = {
            "daySummary": {"currentPhase": 2},
            "dayLog": None,
        }
        result = api.get_menstrual_data_for_date(mock_client, "2026-05-25")
        assert result == {"daySummary": {"currentPhase": 2}, "dayLog": None}

    def test_returns_none_for_bare_empty_dict(self, mock_client: MagicMock) -> None:
        """
        A dict response with neither ``daySummary`` nor ``dayLog`` (the "no cycle data
        for this day" shape) must collapse to ``None``.
        """
        mock_client._connectapi.return_value = {}
        assert api.get_menstrual_data_for_date(mock_client, "2026-05-25") is None

    def test_returns_none_for_non_dict_payload(self, mock_client: MagicMock) -> None:
        """
        Defensive: a non-dict response (list, string, error page) must return ``None``
        instead of raising ``AttributeError`` on ``result.get(...)``.
        """
        for bad_payload in (None, [], "error", 42):
            mock_client._connectapi.return_value = bad_payload
            assert api.get_menstrual_data_for_date(mock_client, "2026-05-25") is None


class TestGetMenstrualCalendarData:
    """
    Tests for ``get_menstrual_calendar_data`` (calendar endpoint with pagination).
    """

    def test_returns_none_when_all_chunks_non_dict(
        self, mock_client: MagicMock
    ) -> None:
        """
        If every chunk's response is non-dict (e.g. an error page on every page of a
        multi-chunk range), the function returns ``None`` instead of raising.
        """
        mock_client._connectapi.return_value = "error"
        result = api.get_menstrual_calendar_data(
            mock_client, "2026-01-01", "2026-06-01"
        )
        assert result is None

    def test_skips_non_dict_chunks_and_merges_dict_chunks(
        self, mock_client: MagicMock
    ) -> None:
        """
        A mixed response sequence (one non-dict chunk, one dict chunk) must skip the bad
        chunk and still return the good chunk's merged content.

        The bad chunk must not abort pagination.
        """
        mock_client._connectapi.side_effect = [
            "error_page",  # First chunk non-dict.
            {  # Second chunk normal.
                "cycleSummaries": [{"startDate": "2026-04-05", "periodLength": 5}],
                "loggedSymptomDays": ["2026-04-05"],
                "loggedOvulationDays": [],
                "loggedNoteDays": [],
            },
        ]
        result = api.get_menstrual_calendar_data(
            mock_client, "2026-01-01", "2026-06-01"
        )
        assert result is not None
        assert result["cycleSummaries"] == [
            {"startDate": "2026-04-05", "periodLength": 5}
        ]
        assert result["loggedSymptomDays"] == ["2026-04-05"]


# ----------------------------------------------------------------------------------------
# RANGE ACTIVITIES
# ----------------------------------------------------------------------------------------


class TestGetActivitiesByDate:
    """
    Tests for ``get_activities_by_date``.
    """

    def test_paginates_until_empty_page(self, mock_client: MagicMock) -> None:
        """
        The loop fetches 20-activity pages until the API returns [].
        """
        # Arrange. First page has 2 activities, second page is empty.
        mock_client._connectapi.side_effect = [
            [{"id": 1}, {"id": 2}],
            [],
        ]

        # Act.
        activities = api.get_activities_by_date(mock_client, "2026-04-01")

        # Assert.
        assert activities == [{"id": 1}, {"id": 2}]
        assert mock_client._connectapi.call_count == 2
        # Each call hits the activities URL.
        for call_args in mock_client._connectapi.call_args_list:
            assert (
                call_args[0][0] == "/activitylist-service/activities/search/activities"
            )

    def test_passes_optional_filters_in_params(self, mock_client: MagicMock) -> None:
        """
        Optional ``enddate``, ``activitytype``, and ``sortorder`` propagate.
        """
        # Arrange.
        mock_client._connectapi.return_value = []
        # Act.
        api.get_activities_by_date(
            mock_client,
            "2026-04-01",
            enddate="2026-04-07",
            activitytype="running",
            sortorder="asc",
        )

        # Assert.
        params = mock_client._connectapi.call_args[1]["params"]
        assert params["startDate"] == "2026-04-01"
        assert params["endDate"] == "2026-04-07"
        assert params["activityType"] == "running"
        assert params["sortOrder"] == "asc"
        assert params["limit"] == "20"

    def test_rejects_malformed_start_date(self, mock_client: MagicMock) -> None:
        """
        A bad start date raises ValueError before any API call.
        """
        with pytest.raises(ValueError):
            api.get_activities_by_date(mock_client, "04/01/2026")
        mock_client._connectapi.assert_not_called()


class TestGetActivityExerciseSets:
    """
    Tests for ``get_activity_exercise_sets``.
    """

    def test_calls_correct_url(self, mock_client: MagicMock) -> None:
        """
        Exercise sets URL contains the activity ID.
        """
        # Arrange.
        mock_client._connectapi.return_value = {"sets": []}
        # Act.
        api.get_activity_exercise_sets(mock_client, 12345)

        # Assert.
        url = mock_client._connectapi.call_args[0][0]
        assert url == "/activity-service/activity/12345/exerciseSets"

    def test_rejects_non_positive_activity_id(self, mock_client: MagicMock) -> None:
        """
        Activity IDs must be positive integers.
        """
        with pytest.raises(ValueError):
            api.get_activity_exercise_sets(mock_client, 0)


# ----------------------------------------------------------------------------------------
# NO-DATE METADATA
# ----------------------------------------------------------------------------------------


class TestGetPersonalRecord:
    """
    Tests for ``get_personal_record``.
    """

    def test_calls_correct_url(self, mock_client: MagicMock) -> None:
        """
        Personal record URL ends in the display name.
        """
        # Act.
        api.get_personal_record(mock_client)

        # Assert.
        url = mock_client._connectapi.call_args[0][0]
        assert url == "/personalrecord-service/personalrecord/prs/stub_user"


class TestGetRacePredictions:
    """
    Tests for ``get_race_predictions``.
    """

    def test_no_args_uses_latest_endpoint(self, mock_client: MagicMock) -> None:
        """
        The openetl hot path calls ``get_race_predictions()`` with no args and expects
        the ``/latest/<display_name>`` endpoint.
        """
        # Act.
        api.get_race_predictions(mock_client)

        # Assert.
        url = mock_client._connectapi.call_args[0][0]
        assert url == "/metrics-service/metrics/racepredictions/latest/stub_user"

    def test_full_args_uses_typed_endpoint(self, mock_client: MagicMock) -> None:
        """
        Providing all three args produces ``/<type>/<display_name>`` plus the date range
        params.
        """
        # Act.
        api.get_race_predictions(mock_client, "2026-01-01", "2026-04-01", _type="daily")
        # Assert.
        url = mock_client._connectapi.call_args[0][0]
        params = mock_client._connectapi.call_args[1]["params"]
        assert url == "/metrics-service/metrics/racepredictions/daily/stub_user"
        assert params == {
            "fromCalendarDate": "2026-01-01",
            "toCalendarDate": "2026-04-01",
        }

    def test_invalid_type_raises(self, mock_client: MagicMock) -> None:
        """
        Unknown ``_type`` values raise ValueError.
        """
        with pytest.raises(ValueError):
            api.get_race_predictions(
                mock_client, "2026-01-01", "2026-04-01", _type="weekly"
            )

    def test_partial_args_raise(self, mock_client: MagicMock) -> None:
        """
        Providing some but not all of the three args raises ValueError.
        """
        with pytest.raises(ValueError):
            api.get_race_predictions(mock_client, "2026-01-01")

    def test_range_longer_than_one_year_raises(self, mock_client: MagicMock) -> None:
        """
        A start-to-end range over one year raises ValueError.
        """
        with pytest.raises(ValueError):
            api.get_race_predictions(
                mock_client, "2024-01-01", "2026-01-01", _type="daily"
            )


class TestGetUserProfile:
    """
    Tests for ``get_user_profile``.
    """

    def test_calls_user_settings_endpoint(self, mock_client: MagicMock) -> None:
        """
        ``get_user_profile`` hits ``/user-settings``, NOT the ``/profile`` endpoint that
        ``_load_profile`` uses.
        """
        # Arrange.
        mock_client._connectapi.return_value = {"id": "12345678"}

        # Act.
        result = api.get_user_profile(mock_client)

        # Assert.
        assert result == {"id": "12345678"}
        url = mock_client._connectapi.call_args[0][0]
        assert url == "/userprofile-service/userprofile/user-settings"


# ----------------------------------------------------------------------------------------
# BINARY DOWNLOAD
# ----------------------------------------------------------------------------------------


class TestDownloadActivity:
    """
    Tests for ``download_activity``.
    """

    def test_original_format_uses_fit_url(self, mock_client: MagicMock) -> None:
        """
        ``ORIGINAL`` format hits the FIT download URL by default.
        """
        # Arrange.
        mock_client._download.return_value = b"FIT_BYTES"

        # Act.
        result = api.download_activity(mock_client, 99999)
        # Assert.
        assert result == b"FIT_BYTES"
        url = mock_client._download.call_args[0][0]
        assert url == "/download-service/files/activity/99999"

    def test_tcx_format_uses_export_tcx_url(self, mock_client: MagicMock) -> None:
        """
        TCX format hits the TCX export URL.
        """
        # Act.
        api.download_activity(mock_client, 99999, ActivityDownloadFormat.TCX)

        # Assert.
        url = mock_client._download.call_args[0][0]
        assert url == "/download-service/export/tcx/activity/99999"

    def test_gpx_format_uses_export_gpx_url(self, mock_client: MagicMock) -> None:
        """
        GPX format hits the GPX export URL.
        """
        # Act.
        api.download_activity(mock_client, 99999, ActivityDownloadFormat.GPX)

        # Assert.
        url = mock_client._download.call_args[0][0]
        assert url == "/download-service/export/gpx/activity/99999"
