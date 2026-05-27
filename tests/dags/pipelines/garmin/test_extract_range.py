"""
Tests for RANGE-typed extraction in dags.pipelines.garmin.extract.

This module covers the per-window RANGE extraction pattern introduced by porting garmin-
health-data#65: RANGE-typed data types now issue ONE API call per window (was N day-by-
day calls), with per-day file splitting downstream so the processor's ``(user, day)``
FileSet abstraction is preserved.

Tests use MagicMock for the Garmin client; no network calls are made.
"""

import json

from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dags.pipelines.garmin.constants import GARMIN_DATA_REGISTRY
from dags.pipelines.garmin.extract import ExtractionFailure, GarminExtractor


@pytest.fixture
def extractor(tmp_path: Path) -> GarminExtractor:
    """
    Build a GarminExtractor over a fixed 5-day window with mocked client and user_id.

    :param tmp_path: Pytest temporary directory fixture.
    :return: GarminExtractor instance ready for RANGE-extraction tests.
    """
    instance = GarminExtractor(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 5),
        ingest_dir=tmp_path,
    )
    instance.user_id = "123"
    instance.garmin_client = MagicMock()
    return instance


class TestExtractRange:
    """
    Tests for ``GarminExtractor._extract_data_by_type`` on RANGE-typed data types.
    """

    def test_range_typed_data_calls_api_once_for_full_window(
        self, extractor: GarminExtractor
    ) -> None:
        """
        RANGE-typed data types must hit the API exactly once for the full window.

        Before the port, the extractor faked RANGE by passing the same date to both
        ``startdate`` and ``enddate`` per day, making N API calls for an N-day window.
        Post-port, ``_extract_range`` makes a single call covering the whole window.
        """
        body_comp = GARMIN_DATA_REGISTRY.get_by_name("BODY_COMPOSITION")
        extractor.garmin_client.get_body_composition.return_value = {
            "dateWeightList": [
                {"calendarDate": "2026-01-01", "weight": 75000.0},
                {"calendarDate": "2026-01-03", "weight": 74800.0},
            ]
        }

        extractor._extract_data_by_type(body_comp, date(2026, 1, 1), date(2026, 1, 5))

        extractor.garmin_client.get_body_composition.assert_called_once_with(
            "2026-01-01", "2026-01-05"
        )

    def test_body_composition_response_is_split_per_day(
        self, extractor: GarminExtractor
    ) -> None:
        """
        ``BODY_COMPOSITION`` per-window responses are split into one file per calendar
        date that had at least one entry.

        Days with no entries produce no file. Each per-day file is a dict with a
        ``dateWeightList`` key containing only the entries whose ``calendarDate``
        matches the bucket date, preserving the per-day file shape the downstream
        processor expects.
        """
        body_comp = GARMIN_DATA_REGISTRY.get_by_name("BODY_COMPOSITION")
        extractor.garmin_client.get_body_composition.return_value = {
            "dateWeightList": [
                {"calendarDate": "2026-01-01", "weight": 75000.0},
                {"calendarDate": "2026-01-01", "weight": 74800.0},
                {"calendarDate": "2026-01-03", "weight": 74500.0},
            ]
        }

        saved = extractor._extract_data_by_type(
            body_comp, date(2026, 1, 1), date(2026, 1, 5)
        )

        # Exactly two files: one for 2026-01-01, one for 2026-01-03.
        # Nothing for 01-02 / 01-04 / 01-05 (no entries).
        assert len(saved) == 2
        names = sorted(p.name for p in saved)
        assert "BODY_COMPOSITION_2026-01-01" in names[0]
        assert "BODY_COMPOSITION_2026-01-03" in names[1]

        # The 2026-01-01 file should contain a dict with dateWeightList of
        # exactly its 2 entries.
        day1_file = next(p for p in saved if "2026-01-01" in p.name)
        with open(day1_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
        assert isinstance(payload, dict)
        assert "dateWeightList" in payload
        assert len(payload["dateWeightList"]) == 2
        for entry in payload["dateWeightList"]:
            assert entry["calendarDate"] == "2026-01-01"

    def test_activities_list_response_is_split_per_day(
        self, extractor: GarminExtractor
    ) -> None:
        """
        ``ACTIVITIES_LIST`` per-window responses are split into one file per local date
        by ``startTimeLocal``.

        Each per-day file is a JSON list of the activity dicts whose ``startTimeLocal``
        date matches the bucket date.
        """
        activities_list = GARMIN_DATA_REGISTRY.get_by_name("ACTIVITIES_LIST")
        extractor.garmin_client.get_activities_by_date.return_value = [
            {"activityId": 1, "startTimeLocal": "2026-01-01T08:00:00"},
            {"activityId": 2, "startTimeLocal": "2026-01-01T18:00:00"},
            {"activityId": 3, "startTimeLocal": "2026-01-03T07:00:00"},
        ]

        saved = extractor._extract_data_by_type(
            activities_list, date(2026, 1, 1), date(2026, 1, 5)
        )

        # Single API call: the perf win.
        extractor.garmin_client.get_activities_by_date.assert_called_once_with(
            "2026-01-01", "2026-01-05"
        )
        # Two files (one per local-date with activities).
        assert len(saved) == 2
        names = sorted(p.name for p in saved)
        assert "ACTIVITIES_LIST_2026-01-01" in names[0]
        assert "ACTIVITIES_LIST_2026-01-03" in names[1]

        # The 2026-01-01 file contains a list of exactly the 2 day-1 activities.
        day1_file = next(p for p in saved if "2026-01-01" in p.name)
        with open(day1_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
        assert isinstance(payload, list)
        assert [a["activityId"] for a in payload] == [1, 2]

        # The 2026-01-03 file contains a list of exactly the 1 day-3 activity.
        day3_file = next(p for p in saved if "2026-01-03" in p.name)
        with open(day3_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
        assert isinstance(payload, list)
        assert [a["activityId"] for a in payload] == [3]

    def test_per_activity_type_returns_empty_from_dispatch(
        self, extractor: GarminExtractor
    ) -> None:
        """
        ``PER_ACTIVITY``-classified data types short-circuit out of the date-driven
        dispatcher because they're iterated per activity_id by
        ``extract_fit_activities``, not per calendar date.

        Regression guard: a routing error (e.g. accidentally sending them through
        ``_extract_range``) would call the API with date params it doesn't accept.
        """
        activity = GARMIN_DATA_REGISTRY.get_by_name("ACTIVITY")
        exercise_sets = GARMIN_DATA_REGISTRY.get_by_name("EXERCISE_SETS")

        for data_type in (activity, exercise_sets):
            result = extractor._extract_data_by_type(
                data_type, date(2026, 1, 1), date(2026, 1, 5)
            )
            assert result == []
        # No API methods on the client were invoked by the dispatcher.
        extractor.garmin_client.download_activity.assert_not_called()
        extractor.garmin_client.get_activity_exercise_sets.assert_not_called()

    def test_splitter_skips_non_dict_entries_in_body_composition(
        self, extractor: GarminExtractor
    ) -> None:
        """
        The splitter must not call ``.get(...)`` on a non-dict ``dateWeightList`` entry.

        A malformed payload that interleaves dicts with strings or other primitives must
        skip the bad entries and process the good ones, mirroring the defensive
        tolerance of ``_load_activities_list_from_disk``.
        """
        body_comp = GARMIN_DATA_REGISTRY.get_by_name("BODY_COMPOSITION")
        extractor.garmin_client.get_body_composition.return_value = {
            "dateWeightList": [
                "not-a-dict",  # Bad entry, should be skipped.
                {"calendarDate": "2026-01-02", "weight": 70000.0},  # Good entry.
                12345,  # Bad entry, should be skipped.
            ]
        }

        saved = extractor._extract_data_by_type(
            body_comp, date(2026, 1, 1), date(2026, 1, 5)
        )

        # Only the one good entry produces a file (2026-01-02).
        assert len(saved) == 1
        assert "BODY_COMPOSITION_2026-01-02" in saved[0].name

    def test_splitter_skips_non_dict_entries_in_activities_list(
        self, extractor: GarminExtractor
    ) -> None:
        """
        The splitter must not call ``.get(...)`` on a non-dict ``ACTIVITIES_LIST``
        entry.

        If the API ever returns a wrapper or interleaves non-dicts, the bad entries are
        skipped and the good ones still land in their per-day files.
        """
        activities_list = GARMIN_DATA_REGISTRY.get_by_name("ACTIVITIES_LIST")
        extractor.garmin_client.get_activities_by_date.return_value = [
            "not-a-dict",
            {"activityId": 1, "startTimeLocal": "2026-01-02T08:00:00"},
            None,
        ]

        saved = extractor._extract_data_by_type(
            activities_list, date(2026, 1, 1), date(2026, 1, 5)
        )

        assert len(saved) == 1
        assert "ACTIVITIES_LIST_2026-01-02" in saved[0].name

    def test_range_failure_records_window_label(
        self, extractor: GarminExtractor
    ) -> None:
        """
        A failure during the per-range API call records the ``"{start}..{end}"`` window
        label in :attr:`failures`, conveying the blast radius of the failure (whole
        window, not one day).
        """
        body_comp = GARMIN_DATA_REGISTRY.get_by_name("BODY_COMPOSITION")
        extractor.garmin_client.get_body_composition.side_effect = RuntimeError(
            "API outage"
        )

        saved = extractor._extract_data_by_type(
            body_comp, date(2026, 1, 1), date(2026, 1, 5)
        )

        assert saved == []
        assert len(extractor.failures) == 1
        failure: ExtractionFailure = extractor.failures[0]
        assert failure.data_type == "BODY_COMPOSITION"
        assert failure.date == "2026-01-01..2026-01-05"
        assert failure.user_id == "123"
        assert "API outage" in failure.error

    def test_range_empty_response_writes_no_file(
        self, extractor: GarminExtractor
    ) -> None:
        """
        A falsy API response yields no saved file and no recorded failure: matches the
        existing DAILY behavior for empty days.
        """
        body_comp = GARMIN_DATA_REGISTRY.get_by_name("BODY_COMPOSITION")
        extractor.garmin_client.get_body_composition.return_value = None

        saved = extractor._extract_data_by_type(
            body_comp, date(2026, 1, 1), date(2026, 1, 5)
        )

        assert saved == []
        assert extractor.failures == []

    def test_menstrual_cycle_summary_writes_single_file_stamped_end_date(
        self, extractor: GarminExtractor
    ) -> None:
        """
        MENSTRUAL_CYCLE_SUMMARY is an unsplittable RANGE type: the wipe-and-replace
        policy needs to see the whole new set in one transaction, so the response is
        written as a single file stamped with end_date.
        """
        extractor.start_date = date(2026, 1, 1)
        extractor.end_date = date(2026, 3, 1)
        extractor.garmin_client.get_menstrual_calendar_data.return_value = {
            "cycleSummaries": [
                {"startDate": "2026-01-05", "periodLength": 5, "predictedCycle": False},
                {"startDate": "2026-02-05", "periodLength": 5, "predictedCycle": True},
            ]
        }

        summary = GARMIN_DATA_REGISTRY.get_by_name("MENSTRUAL_CYCLE_SUMMARY")
        files = extractor._extract_data_by_type(
            summary, date(2026, 1, 1), date(2026, 3, 1)
        )

        assert len(files) == 1
        assert "MENSTRUAL_CYCLE_SUMMARY_2026-03-01" in files[0].name
