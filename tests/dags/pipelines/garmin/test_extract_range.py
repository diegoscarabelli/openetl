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
            "dailyWeightSummaries": [
                {
                    "summaryDate": "2026-01-01",
                    "allWeightMetrics": [{"weight": 75000.0}],
                },
                {
                    "summaryDate": "2026-01-03",
                    "allWeightMetrics": [{"weight": 74800.0}],
                },
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
        ``BODY_COMPOSITION`` per-window responses are split into one file per local day
        that had at least one weigh-in.

        Days with no weigh-in produce no file. Each per-day file is a dict with a
        ``dateWeightList`` key holding every weigh-in from that day's
        ``allWeightMetrics``, preserving the per-day file shape the downstream processor
        expects.
        """
        body_comp = GARMIN_DATA_REGISTRY.get_by_name("BODY_COMPOSITION")
        extractor.garmin_client.get_body_composition.return_value = {
            "dailyWeightSummaries": [
                {
                    "summaryDate": "2026-01-01",
                    "allWeightMetrics": [
                        {"timestampGMT": 1, "weight": 75000.0},
                        {"timestampGMT": 2, "weight": 74800.0},
                    ],
                },
                {
                    "summaryDate": "2026-01-03",
                    "allWeightMetrics": [{"timestampGMT": 3, "weight": 74500.0}],
                },
            ]
        }

        saved = extractor._extract_data_by_type(
            body_comp, date(2026, 1, 1), date(2026, 1, 5)
        )

        # Exactly two files: one for 2026-01-01, one for 2026-01-03.
        # Nothing for 01-02 / 01-04 / 01-05 (no weigh-ins).
        assert len(saved) == 2
        names = sorted(p.name for p in saved)
        assert "BODY_COMPOSITION_2026-01-01" in names[0]
        assert "BODY_COMPOSITION_2026-01-03" in names[1]

        # The 2026-01-01 file should contain a dict with dateWeightList of
        # exactly its 2 weigh-ins.
        day1_file = next(p for p in saved if "2026-01-01" in p.name)
        with open(day1_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
        assert isinstance(payload, dict)
        assert "dateWeightList" in payload
        assert len(payload["dateWeightList"]) == 2
        assert {e["weight"] for e in payload["dateWeightList"]} == {75000.0, 74800.0}

    def test_body_composition_multiple_weighins_same_day_all_preserved(
        self, extractor: GarminExtractor
    ) -> None:
        """
        Every weigh-in on a multi-weigh-in day is preserved (the #74 fix).

        The ``daterangesnapshot`` endpoint returned only one representative weigh-in per
        day; ``weight/range?includeAll=true`` returns them all under
        ``allWeightMetrics``, and the splitter must land every one in that day's file.
        """
        body_comp = GARMIN_DATA_REGISTRY.get_by_name("BODY_COMPOSITION")
        extractor.garmin_client.get_body_composition.return_value = {
            "dailyWeightSummaries": [
                {
                    "summaryDate": "2026-01-02",
                    "allWeightMetrics": [
                        {"timestampGMT": 1, "weight": 70000.0},
                        {"timestampGMT": 2, "weight": 70100.0},
                        {"timestampGMT": 3, "weight": 69900.0},
                    ],
                }
            ]
        }

        saved = extractor._extract_data_by_type(
            body_comp, date(2026, 1, 1), date(2026, 1, 5)
        )

        assert len(saved) == 1
        with open(saved[0], "r", encoding="utf-8") as f:
            payload = json.load(f)
        assert len(payload["dateWeightList"]) == 3
        assert {e["weight"] for e in payload["dateWeightList"]} == {
            70000.0,
            70100.0,
            69900.0,
        }

    def test_body_composition_grouped_by_summary_date_not_utc_timestamp(
        self, extractor: GarminExtractor
    ) -> None:
        """
        Weigh-ins are grouped by Garmin's local ``summaryDate``, not each weigh-in's UTC
        ``timestampGMT``.

        Two weigh-ins on the same local day whose UTC timestamps straddle midnight must
        land in one per-day file. Grouping by ``timestampGMT`` would split them across
        two days; grouping by ``summaryDate`` keeps them together.
        """
        body_comp = GARMIN_DATA_REGISTRY.get_by_name("BODY_COMPOSITION")
        # The two timestampGMT values fall on different UTC calendar days, but Garmin
        # buckets both under the same local ``summaryDate``.
        extractor.garmin_client.get_body_composition.return_value = {
            "dailyWeightSummaries": [
                {
                    "summaryDate": "2026-01-02",
                    "allWeightMetrics": [
                        {"timestampGMT": 1767394800000, "weight": 70000.0},
                        {"timestampGMT": 1767416400000, "weight": 70100.0},
                    ],
                }
            ]
        }

        saved = extractor._extract_data_by_type(
            body_comp, date(2026, 1, 1), date(2026, 1, 5)
        )

        assert len(saved) == 1
        assert "BODY_COMPOSITION_2026-01-02" in saved[0].name
        with open(saved[0], "r", encoding="utf-8") as f:
            payload = json.load(f)
        assert len(payload["dateWeightList"]) == 2

    def test_activities_list_response_is_split_per_day(
        self, extractor: GarminExtractor
    ) -> None:
        """
        ``ACTIVITIES_LIST`` per-window responses are split into one file per day in the
        window by ``startTimeLocal``.

        Every day in the window gets a file. Days with at least one activity get a non-
        empty JSON list; days with zero activities get an empty list ([]). The per-day
        completeness is required by ``_load_activities_list_from_disk`` to trust the on-
        disk cache and skip a second API call when ``extract_fit_activities`` runs.
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
        # Five files: one per day in the 5-day window.
        assert len(saved) == 5
        names = sorted(p.name for p in saved)
        for day_iso in (
            "2026-01-01",
            "2026-01-02",
            "2026-01-03",
            "2026-01-04",
            "2026-01-05",
        ):
            assert any(f"ACTIVITIES_LIST_{day_iso}" in n for n in names)

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

        # The 2026-01-02 file (no activities) is a present-but-empty list, not
        # absent. Required so _load_activities_list_from_disk sees full window
        # coverage and the FIT downloader can use the on-disk cache.
        day2_file = next(p for p in saved if "2026-01-02" in p.name)
        with open(day2_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
        assert payload == []

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
        The splitter must tolerate malformed shapes: a non-dict daily summary, and non-
        dict entries inside ``allWeightMetrics``, are skipped rather than raising on
        ``.get(...)``.
        """
        body_comp = GARMIN_DATA_REGISTRY.get_by_name("BODY_COMPOSITION")
        extractor.garmin_client.get_body_composition.return_value = {
            "dailyWeightSummaries": [
                "not-a-dict",  # Bad summary, should be skipped.
                {
                    "summaryDate": "2026-01-02",
                    "allWeightMetrics": [
                        "not-a-dict",  # Bad entry, should be skipped.
                        {"timestampGMT": 1, "weight": 70000.0},  # Good entry.
                        12345,  # Bad entry, should be skipped.
                    ],
                },
            ]
        }

        saved = extractor._extract_data_by_type(
            body_comp, date(2026, 1, 1), date(2026, 1, 5)
        )

        # Only the one good entry produces a file (2026-01-02).
        assert len(saved) == 1
        assert "BODY_COMPOSITION_2026-01-02" in saved[0].name
        with open(saved[0], "r", encoding="utf-8") as f:
            payload = json.load(f)
        assert len(payload["dateWeightList"]) == 1

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

        # 5 files (one per day in window) — bad entries skipped, good entry in
        # the 01-02 bucket, the other 4 days are present-but-empty.
        assert len(saved) == 5
        day2_file = next(p for p in saved if "2026-01-02" in p.name)
        with open(day2_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
        assert isinstance(payload, list)
        assert [a["activityId"] for a in payload] == [1]

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

    def test_running_tolerance_single_call_for_full_window(
        self, extractor: GarminExtractor
    ) -> None:
        """
        RUNNING_TOLERANCE is RANGE-typed: one API call covers the whole window.
        """
        rt = GARMIN_DATA_REGISTRY.get_by_name("RUNNING_TOLERANCE")
        extractor.garmin_client.get_running_tolerance.return_value = [
            {"calendarDate": "2026-01-01", "totalImpactLoad": 1000},
            {"calendarDate": "2026-01-03", "totalImpactLoad": 1200},
        ]

        extractor._extract_data_by_type(rt, date(2026, 1, 1), date(2026, 1, 5))

        extractor.garmin_client.get_running_tolerance.assert_called_once_with(
            "2026-01-01", "2026-01-05"
        )

    def test_running_tolerance_response_is_split_per_day(
        self, extractor: GarminExtractor
    ) -> None:
        """
        RUNNING_TOLERANCE per-window responses split into one file per calendar day that
        has a row (sparse: days with no row produce no file).

        Each per-day file is a list of that day's running-tolerance rows.
        """
        rt = GARMIN_DATA_REGISTRY.get_by_name("RUNNING_TOLERANCE")
        extractor.garmin_client.get_running_tolerance.return_value = [
            {"calendarDate": "2026-01-01", "totalImpactLoad": 1000},
            {"calendarDate": "2026-01-03", "totalImpactLoad": 1200},
        ]

        saved = extractor._extract_data_by_type(rt, date(2026, 1, 1), date(2026, 1, 5))

        # Two files: 2026-01-01 and 2026-01-03; nothing for the empty days.
        assert len(saved) == 2
        names = sorted(p.name for p in saved)
        assert "RUNNING_TOLERANCE_2026-01-01" in names[0]
        assert "RUNNING_TOLERANCE_2026-01-03" in names[1]

        day1_file = next(p for p in saved if "2026-01-01" in p.name)
        with open(day1_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
        assert isinstance(payload, list)
        assert len(payload) == 1
        assert payload[0]["totalImpactLoad"] == 1000

    def test_running_tolerance_empty_response_writes_no_file(
        self, extractor: GarminExtractor
    ) -> None:
        """
        A falsy (``None``) running-tolerance response (account without a compatible
        watch) yields no file and no recorded failure.
        """
        rt = GARMIN_DATA_REGISTRY.get_by_name("RUNNING_TOLERANCE")
        extractor.garmin_client.get_running_tolerance.return_value = None

        saved = extractor._extract_data_by_type(rt, date(2026, 1, 1), date(2026, 1, 5))

        assert saved == []
        assert extractor.failures == []

    def test_running_tolerance_skips_rows_without_calendar_date(
        self, extractor: GarminExtractor
    ) -> None:
        """
        Rows missing ``calendarDate`` (or non-dict rows) are skipped rather than
        raising; only the well-formed row produces a file.
        """
        rt = GARMIN_DATA_REGISTRY.get_by_name("RUNNING_TOLERANCE")
        extractor.garmin_client.get_running_tolerance.return_value = [
            "not-a-dict",
            {"totalImpactLoad": 999},  # No calendarDate: skipped.
            {"calendarDate": "2026-01-02", "totalImpactLoad": 1100},  # Good.
        ]

        saved = extractor._extract_data_by_type(rt, date(2026, 1, 1), date(2026, 1, 5))

        assert len(saved) == 1
        assert "RUNNING_TOLERANCE_2026-01-02" in saved[0].name

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
