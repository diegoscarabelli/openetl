"""
Garmin Connect data extraction module.

Extracts FIT activity files and JSON Garmin data from Garmin Connect API and saves them
to the ingest directory for further processing by the ETL pipeline. Supports multiple
Garmin Connect accounts by discovering token subdirectories in the base token directory.
"""

import json
import socket
import time
import zipfile
import io

from dataclasses import dataclass
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Union

import fire
import pendulum
import requests
from airflow.sdk.exceptions import AirflowFailException, AirflowSkipException

from dags.lib.logging_utils import LOGGER
from dags.pipelines.garmin.constants import (
    APIMethodTimeParam,
    GarminDataType,
    GARMIN_DATA_REGISTRY,
)
from dags.pipelines.garmin.garmin_client import GarminClient
from dags.pipelines.garmin.garmin_client.exceptions import GarminConnectionError

# Exception classes considered transient (worth retrying with backoff). All
# represent network or transport-level failures that typically self-heal in
# seconds. Application-level errors (parse failures, ValueError, etc.) are
# excluded because retries won't help.
_TRANSIENT_API_EXCEPTIONS: tuple = (
    GarminConnectionError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    socket.gaierror,
)

# Backoff schedule applied before each retry attempt. With three entries the
# call gets a total of four chances (1 initial + 3 retries) over ~40s in the
# worst case, comfortably absorbing typical DNS hiccups and brief outages.
_RETRY_BACKOFFS: tuple = (2.0, 8.0, 30.0)

# Data types whose already-extracted past days can change retroactively when the user
# edits history in Garmin Connect (e.g. moving a menstrual period start recomputes
# ``dayInCycle`` for every following day). Maps the data type name to a look-back window
# in days; a routine run re-fetches that trailing window so the edits are picked up and
# overwritten, not just the narrow incremental slice. 90 days comfortably covers a full
# cycle's worth of cascade.
_RETROACTIVE_LOOKBACK_DAYS: Dict[str, int] = {
    "MENSTRUAL_CYCLE_DAY": 90,
}


def _retroactive_lookback_start(
    data_type: GarminDataType, start_date: date, end_date: date
) -> date:
    """
    Extend ``start_date`` backward for data types that need a retroactive-edit refresh.

    Returns the earlier of the requested ``start_date`` and ``end_date - lookback`` for
    data types registered in ``_RETROACTIVE_LOOKBACK_DAYS``. The start only ever moves
    earlier, so an explicit wider backfill window is left untouched. Data types not in
    the registry are returned unchanged.

    :param data_type: The data type being extracted.
    :param start_date: The requested (e.g. incremental) start date.
    :param end_date: The extraction end date.
    :return: The effective start date to extract from.
    """
    lookback = _RETROACTIVE_LOOKBACK_DAYS.get(data_type.name)
    if lookback is None:
        return start_date
    return min(start_date, end_date - timedelta(days=lookback))


def _with_retries(fn: Callable, *args, **kwargs):
    """
    Call ``fn(*args, **kwargs)`` with exponential-backoff retries on transient network
    errors.

    Retries only on the connection / DNS / timeout exception classes listed in
    ``_TRANSIENT_API_EXCEPTIONS``. Other exceptions propagate immediately so the
    caller's broader try/except (per-date isolation in
    :meth:`GarminExtractor._extract_day_by_day`, per-window isolation in
    :meth:`GarminExtractor._extract_range`, or per-activity isolation in
    :meth:`GarminExtractor.extract_fit_activities`) can record the failure once and move
    on.

    :param fn: Callable to invoke.
    :param args: Positional arguments forwarded to ``fn``.
    :param kwargs: Keyword arguments forwarded to ``fn``.
    :return: Whatever ``fn`` returns on success.
    :raises Exception: The last transient exception if all retries are exhausted, or any
        non-transient exception immediately.
    """
    total_attempts = 1 + len(_RETRY_BACKOFFS)
    for attempt in range(total_attempts):
        try:
            return fn(*args, **kwargs)
        except _TRANSIENT_API_EXCEPTIONS as e:
            if attempt >= len(_RETRY_BACKOFFS):
                # Final attempt: re-raise to preserve the original traceback.
                raise
            backoff = _RETRY_BACKOFFS[attempt]
            LOGGER.warning(
                f"⏳ Transient error ({type(e).__name__}: {e}); "
                f"retrying in {backoff:.0f}s "
                f"(attempt {attempt + 2}/{total_attempts})..."
            )
            time.sleep(backoff)


@dataclass
class ExtractionFailure:
    """
    A single extraction failure recorded by the extractor for end-of-run reporting.

    :ivar user_id: Garmin user ID the failure belongs to. Populated when the failure is
        appended (the ``GarminExtractor`` knows its own ``user_id`` post-authentication)
        so a multi-account ``extract()`` task can attribute every failure to the right
        account in the end-of-run summary. May be ``""`` if the failure occurred before
        authentication.
    :ivar data_type: Garmin data type name (e.g. ``"SLEEP"``, ``"ACTIVITY"``).
    :ivar date: Date context for the failure. Typically an ISO date string (``"YYYY-MM-
        DD"``) for per-day (DAILY-type) failures, a range string ``"<start>..<end>"``
        for any RANGE-type failure (the API call is per-window, so the failure label
        covers the whole window even when the response would have been split into per-
        day files on success), or ``""`` when no date context applies (per-data-type or
        per-activity failures).
    :ivar activity_id: Activity ID as a string for per-activity failures, or ``""``
        otherwise.
    :ivar error: Human-readable error description (typically ``"<ExceptionType>:
        <message>"``).
    """

    user_id: str
    data_type: str
    date: str
    activity_id: str
    error: str


class GarminExtractor:
    """
    Handles Garmin Connect data extraction with shared state and methods.

    Downloads FIT activity files and JSON Garmin data from Garmin Connect for the
    specified date range. Files are saved with standardized naming conventions to the
    ingest directory for downstream processing.

    Authentication uses pre-existing tokens. If authentication fails, run
    refresh_garmin_tokens.py to obtain fresh tokens.

    The extraction includes:
    - FIT activity files (binary format).
    - Garmin data (JSON format): sleep, HRV, stress, body battery, respiration,
      SpO2, heart rate, resting heart rate, training metrics, steps, floors, etc.
    """

    def __init__(
        self,
        start_date: date,
        end_date: date,
        ingest_dir: Path,
        data_types: Optional[List[str]] = None,
    ) -> None:
        """
        Initialize the Garmin extractor with date range and target directory.

        :param start_date: Start date for data extraction (inclusive).
        :param end_date: End date for data extraction (inclusive).
        :param ingest_dir: Directory to save extracted files.
        :param data_types: Optional list of data type names to extract (e.g., ['SLEEP',
            'HRV']). If None, extracts all available data types.
        """
        self.start_date = start_date
        self.end_date = end_date
        self.ingest_dir = ingest_dir
        self.data_types = data_types
        self.garmin_client = None
        self.user_id = None
        self.failures: List[ExtractionFailure] = []

    def authenticate(self, token_store_dir: str) -> None:
        """
        Authenticate with Garmin Connect using pre-existing tokens and get user ID.

        Loads OAuth tokens previously saved by refresh_garmin_tokens.py via the
        vendored ``GarminClient.from_tokens()`` classmethod. The vendored client
        handles token validation, transparent refresh on near-expiry or 401, and
        persists rotated refresh tokens back to disk.

        Sets both self.garmin_client and self.user_id upon successful authentication.

        Token Lifecycle:
        - Tokens are stored in ~/.garminconnect/<user_id>/garmin_tokens.json per account.
        - Access tokens (~18h) are auto-refreshed using the refresh token (30 days).
        - Refresh tokens rotate on each use; updated tokens are persisted to disk.
        - No credentials (email/password) required once valid tokens exist.

        When to run refresh_garmin_tokens.py:
        - Initial setup (no tokens exist).
        - Pipeline idle for 30+ days (refresh token expired).
        - Authentication errors occur in the pipeline.

        :param token_store_dir: Directory containing authentication tokens for a
            single Garmin account (e.g. ``~/.garminconnect/<user_id>/``). The
            vendored client appends ``garmin_tokens.json`` to this path when it
            receives a directory, so the base multi-account directory
            ``~/.garminconnect/`` is not a valid value: callers must pass the
            per-user subdirectory for the account being extracted.
        :raises RuntimeError: If tokens are missing, expired, or invalid. Run
            refresh_garmin_tokens.py to resolve authentication issues.
        """
        token_store_path = Path(token_store_dir).expanduser()
        LOGGER.info("🔐 Authenticating with Garmin Connect using saved tokens.")

        try:
            # Load existing tokens, populate display_name/full_name from
            # /userprofile-service/socialProfile.
            self.garmin_client = GarminClient.from_tokens(token_store_path)
            LOGGER.info(
                f"✅ Authentication successful for "
                f"{self.garmin_client.full_name} using saved tokens."
            )
        except Exception as e:
            error_msg = (
                f"❌ Garmin authentication failed: {str(e)}\n\n"
                "🔧 To resolve this issue, run the token refresh script:\n"
                "   python dags/pipelines/garmin/utility_scripts/"
                "   refresh_garmin_tokens.py\n\n"
                "📄 This script will:\n"
                "   - Guide you through Garmin Connect login.\n"
                "   - Handle MFA if enabled on your account.\n"
                "   - Save fresh tokens for pipeline use.\n\n"
                f"📁 Expected token location: {token_store_path}."
            )
            LOGGER.error(error_msg)
            raise RuntimeError(error_msg) from e

        # Get user ID for later use.
        self.user_id = self.garmin_client.get_user_profile().get("id")

    def _get_data_types_to_extract(
        self, data_types: Optional[List[str]] = None
    ) -> List[GarminDataType]:
        """
        Get the list of data types to extract.

        :param data_types: Optional list of data type names to extract. If None, returns
            all registered data types. If empty list, returns empty list (no registered
            data type extraction).
        :return: List of GarminDataType objects to extract.
        :raises ValueError: If any requested data type names are not found in registry.
        """
        if data_types is None:
            return GARMIN_DATA_REGISTRY.all_data_types

        # Handle explicit empty list: user wants no Garmin data types.
        if len(data_types) == 0:
            LOGGER.info("Empty data_types list provided.")
            return []

        # Validate and retrieve requested data types.
        filtered_data_types = []
        invalid_names = []

        for name in data_types:
            data_type = GARMIN_DATA_REGISTRY.get_by_name(name)
            if data_type is None:
                invalid_names.append(name)
            else:
                filtered_data_types.append(data_type)

        if invalid_names:
            available_names = [dt.name for dt in GARMIN_DATA_REGISTRY.all_data_types]
            raise ValueError(
                f"Invalid data type names: {invalid_names}. "
                f"Available data types: {sorted(available_names)}."
            )

        return filtered_data_types

    def extract_garmin_data(self) -> List[Path]:
        """
        Extract Garmin data from Garmin Connect using GARMIN_DATA_REGISTRY data types.
        Allows for flexible configuration of data types and API methods.

        This method always processes dates inclusively - both start_date and
        end_date are included in the extraction. The extract() function handles any
        exclusion logic before passing dates to the Extractor class.

        :return: List of saved JSON file paths.
        """
        # Get the data types to extract (all or filtered subset).
        data_types_to_extract = self._get_data_types_to_extract(self.data_types)

        # Early return if empty list (no data types to extract).
        if len(data_types_to_extract) == 0:
            LOGGER.info("Skipping Garmin data extraction: no data types to process.")
            return []

        if self.data_types:
            data_type_names = [dt.name for dt in data_types_to_extract]
            LOGGER.info(
                f"Fetching data from Garmin Connect for selected data types from "
                f"the GarminDataRegistry "
                f"(start: {self.start_date}, end: {self.end_date} inclusive): "
                f"{data_type_names}."
            )
        else:
            LOGGER.info(
                f"Fetching from Garmin Connect for all data types from "
                f"the GarminDataRegistry "
                f"(start: {self.start_date}, end: {self.end_date} inclusive)..."
            )

        # Extract Garmin data by iterating over selected data types.
        # Per-data-type try/except so one bad type (e.g. NO_DATE call that
        # raises, or a structural error escaping the inner per-date layer)
        # doesn't abort the rest of the account's extraction.
        saved_files = []

        for data_type in data_types_to_extract:
            try:
                files = self._extract_data_by_type(
                    data_type, self.start_date, self.end_date
                )
                saved_files.extend(files)
            except Exception as e:
                LOGGER.error(
                    f"⚠️ {data_type.name} extraction failed entirely: "
                    f"{type(e).__name__}: {e}. Continuing with next data type.",
                    exc_info=True,
                )
                self.failures.append(
                    ExtractionFailure(
                        user_id=self.user_id or "",
                        data_type=data_type.name,
                        date="",
                        activity_id="",
                        error=f"{type(e).__name__}: {e}",
                    )
                )

        return saved_files

    def _extract_day_by_day(
        self, data_type: GarminDataType, start_date: date, end_date: date
    ) -> List[Path]:
        """
        Extract a DAILY-typed Garmin data type one day at a time with per-date error
        isolation.

        Each per-day API call goes through ``_with_retries`` so transient network blips
        absorb silently. A failure that exhausts retries is logged and recorded in
        :attr:`failures`; extraction continues with the next date so a single bad day
        never aborts the rest of the date range. RANGE-typed data types are extracted by
        :meth:`_extract_range` with a single API call covering the full window.

        :param data_type: GarminDataType with DAILY time parameter.
        :param start_date: Start date for data extraction (inclusive).
        :param end_date: End date for data extraction (inclusive).
        :return: List of saved file paths.
        """
        saved_files = []
        current_date = start_date

        while current_date <= end_date:  # Inclusive end_date.
            LOGGER.info(
                f"Fetching {data_type.emoji} {data_type.name} data for {current_date}."
            )
            date_str = current_date.strftime("%Y-%m-%d")

            try:
                api_method = getattr(self.garmin_client, data_type.api_method)
                data = _with_retries(api_method, date_str)

                if data:
                    saved_files.extend(
                        self._save_garmin_data(data, data_type, current_date)
                    )
                else:
                    LOGGER.warning(
                        f"⚠️ {data_type.emoji} {data_type.name}: "
                        f"No data for {current_date}."
                    )
            except Exception as e:
                LOGGER.error(
                    f"⚠️ {data_type.name} {date_str} failed: "
                    f"{type(e).__name__}: {e}. Continuing with next date.",
                    exc_info=True,
                )
                self.failures.append(
                    ExtractionFailure(
                        user_id=self.user_id or "",
                        data_type=data_type.name,
                        date=date_str,
                        activity_id="",
                        error=f"{type(e).__name__}: {e}",
                    )
                )

            current_date += timedelta(days=1)
            time.sleep(0.1)  # Rate limiting.

        return saved_files

    def _extract_range(
        self, data_type: GarminDataType, start_date: date, end_date: date
    ) -> List[Path]:
        """
        Extract a RANGE-typed Garmin data type with ONE API call for the full window.

        The Garmin endpoints behind RANGE-typed wrappers accept a native date range and
        return all matching rows in one response. Calling them once per day with
        ``start = end`` wastes API quota and multiplies disk I/O. Post-fetch, types
        whose rows are naturally per-day (``BODY_COMPOSITION``, ``ACTIVITIES_LIST``)
        are split into per-day files via
        :meth:`_split_range_response_to_per_day_files`, preserving the downstream
        ``(user, day)`` FileSet abstraction the processor depends on.

        Failure isolation is per-range (one API call): a failure records
        ``"{start}..{end}"`` in :attr:`failures`.

        :param data_type: GarminDataType with RANGE time parameter.
        :param start_date: Inclusive start date for the API call.
        :param end_date: Inclusive end date for the API call.
        :return: List of saved file paths (one per day for splittable types, one
            stamped end_date for unsplittable RANGE types).
        """
        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")
        LOGGER.info(
            f"Fetching {data_type.emoji} {data_type.name} data for "
            f"{start_str}..{end_str} (single call)."
        )

        try:
            api_method = getattr(self.garmin_client, data_type.api_method)
            data = _with_retries(api_method, start_str, end_str)
        except Exception as e:
            LOGGER.error(
                f"⚠️ {data_type.name} {start_str}..{end_str} failed: "
                f"{type(e).__name__}: {e}.",
                exc_info=True,
            )
            self.failures.append(
                ExtractionFailure(
                    user_id=self.user_id or "",
                    data_type=data_type.name,
                    date=f"{start_str}..{end_str}",
                    activity_id="",
                    error=f"{type(e).__name__}: {e}",
                )
            )
            return []

        # Splittable RANGE types route to the splitter even on an empty payload
        # (e.g. ACTIVITIES_LIST returning []), because the splitter writes a
        # per-day empty-list file for ACTIVITIES_LIST so the on-disk coverage
        # check used by extract_fit_activities trusts the cache. Only bail on
        # None (transport-level "no response"), not on empty-but-valid data.
        # (BODY_COMPOSITION and RUNNING_TOLERANCE split sparsely: their wrappers
        # normalize no-data to None, so they bail above and never reach here empty.)
        if data_type.name in (
            "BODY_COMPOSITION",
            "ACTIVITIES_LIST",
            "RUNNING_TOLERANCE",
        ):
            if data is None:
                LOGGER.warning(
                    f"⚠️ {data_type.emoji} {data_type.name}: No data for "
                    f"{start_str}..{end_str}."
                )
                return []
            return self._split_range_response_to_per_day_files(
                data, data_type, start_date, end_date
            )

        # Unsplittable RANGE types (a single-payload response that should not be
        # split per day) skip on any falsy payload and otherwise get one file
        # stamped end_date.
        if not data:
            LOGGER.warning(
                f"⚠️ {data_type.emoji} {data_type.name}: No data for "
                f"{start_str}..{end_str}."
            )
            return []
        return self._save_garmin_data(data, data_type, end_date)

    def _split_range_response_to_per_day_files(
        self,
        data: Union[Dict, List],
        data_type: GarminDataType,
        start_date: date,
        end_date: date,
    ) -> List[Path]:
        """
        Split a per-window RANGE response into per-day files.

        ``BODY_COMPOSITION``'s response is a dict with a ``dailyWeightSummaries`` key
        (each summary carries a local ``summaryDate`` and an ``allWeightMetrics`` list
        of that day's weigh-ins); the splitter is sparse — days with no weigh-in produce
        no file (the FileSet abstraction tolerates a ``(user, day)`` with no data).
        Grouping by ``summaryDate`` (not each weigh-in's UTC ``timestampGMT``) keeps
        multiple weigh-ins on the same local day in one file even when their UTC
        timestamps straddle midnight.

        ``ACTIVITIES_LIST``'s response is a list of activity dicts (each has
        ``startTimeLocal`` whose date prefix is the local calendar date); the splitter
        is dense — every day in ``[start_date, end_date]`` produces a file, with an
        empty list ``[]`` for days that have no activities. This density is required by
        :meth:`_load_activities_list_from_disk`'s on-disk coverage check: without a file
        per day, the FIT downloader would fall back to a redundant live API call.

        ``RUNNING_TOLERANCE``'s response is a list of per-day dicts (each has
        ``calendarDate``); the splitter is sparse — only days with a row produce a file,
        each holding that day's list of running-tolerance rows.

        :param data: Per-window response payload (dict for BODY_COMPOSITION, list for
            ACTIVITIES_LIST and RUNNING_TOLERANCE).
        :param data_type: BODY_COMPOSITION, ACTIVITIES_LIST, or RUNNING_TOLERANCE data
            type.
        :param start_date: Inclusive start date of the requested window.
        :param end_date: Inclusive end date of the requested window.
        :return: List of saved per-day file paths.
        :raises ValueError: If ``data_type.name`` is not BODY_COMPOSITION,
            ACTIVITIES_LIST, or RUNNING_TOLERANCE.
        """
        if data_type.name == "BODY_COMPOSITION":
            dict_buckets: Dict[date, dict] = {}
            # Defensive: BODY_COMPOSITION's API contract is a dict wrapper, but if
            # an unexpected shape (list, string) ever reaches the splitter, fall
            # back to "no summaries" instead of raising on .get(). Explicit parens
            # make the short-circuit intent unambiguous to readers.
            summaries = (
                (data.get("dailyWeightSummaries") or [])
                if isinstance(data, dict)
                else []
            )
            for summary in summaries:
                # Defensive: skip non-dict summaries rather than raise on
                # summary.get(...) below.
                if not isinstance(summary, dict):
                    continue
                summary_date_str = summary.get("summaryDate")
                if not summary_date_str:
                    continue
                try:
                    cal_date = date.fromisoformat(str(summary_date_str)[:10])
                except ValueError:
                    continue
                if not (start_date <= cal_date <= end_date):
                    continue
                # Group by Garmin's local ``summaryDate`` (not each weigh-in's UTC
                # ``timestampGMT``) so multiple weigh-ins on the same local day land
                # in one file even when their UTC timestamps straddle midnight. Skip
                # non-dict weigh-in entries rather than raise on the processor side.
                metrics = [
                    m
                    for m in (summary.get("allWeightMetrics") or [])
                    if isinstance(m, dict)
                ]
                if not metrics:
                    continue
                bucket = dict_buckets.setdefault(cal_date, {"dateWeightList": []})
                bucket["dateWeightList"].extend(metrics)
            buckets: Dict[date, Union[dict, list]] = dict_buckets
        elif data_type.name == "ACTIVITIES_LIST":
            # Pre-populate every day in the window with an empty list so days
            # without activities still produce a (zero-byte-list) file.
            # _load_activities_list_from_disk requires one file per day to
            # trust the on-disk cache and skip a second API call in
            # extract_fit_activities. Without this, any zero-activity day in
            # the window would force the FIT downloader to re-hit the API.
            list_buckets: Dict[date, list] = {
                start_date + timedelta(days=i): []
                for i in range((end_date - start_date).days + 1)
            }
            for activity in data or []:
                # Defensive: skip non-dict entries (e.g. unexpected wrapper
                # shapes) rather than raise on activity.get(...). Mirrors
                # _load_activities_list_from_disk's tolerance.
                if not isinstance(activity, dict):
                    continue
                start_local = activity.get("startTimeLocal", "")
                cal_date_str = start_local[:10]
                try:
                    cal_date = date.fromisoformat(cal_date_str)
                except ValueError:
                    continue
                if not (start_date <= cal_date <= end_date):
                    continue
                list_buckets[cal_date].append(activity)
            buckets = list_buckets
        elif data_type.name == "RUNNING_TOLERANCE":
            # Sparse per-day split: the aggregation=daily response is a list with one
            # row per calendar day (``calendarDate``). Days with no row produce no file
            # (unlike ACTIVITIES_LIST, which is dense). Skip non-dict rows and rows
            # without a parseable ``calendarDate`` rather than raising.
            rt_buckets: Dict[date, list] = {}
            for row in data or []:
                if not isinstance(row, dict):
                    continue
                cal_date_str = row.get("calendarDate")
                if not cal_date_str:
                    continue
                try:
                    cal_date = date.fromisoformat(str(cal_date_str)[:10])
                except ValueError:
                    continue
                if not (start_date <= cal_date <= end_date):
                    continue
                rt_buckets.setdefault(cal_date, []).append(row)
            buckets = rt_buckets
        else:
            raise ValueError(
                f"_split_range_response_to_per_day_files called with unsupported "
                f"type: {data_type.name}."
            )

        saved: List[Path] = []
        for cal_date, payload in sorted(buckets.items()):
            saved.extend(self._save_garmin_data(payload, data_type, cal_date))
        return saved

    def _extract_data_by_type(
        self, data_type: GarminDataType, start_date: date, end_date: date
    ) -> List[Path]:
        """
        Extract Garmin data for a specific type.

        Dispatches by ``api_method_time_param``: DAILY loops day-by-day, RANGE makes one
        call covering the full requested window, NO_DATE makes one call with no date
        parameters, PER_ACTIVITY is handled separately by :meth:`extract_fit_activities`
        and short-circuits here.

        :param data_type: GarminDataType defining the extraction parameters.
        :param start_date: Start date for data extraction (inclusive).
        :param end_date: End date for data extraction (inclusive).
        :return: List of saved file paths.
        :raises ValueError: If ``data_type.api_method_time_param`` is not one of the
            four supported variants.
        """
        # PER_ACTIVITY types iterate per activity_id, not per date. They are
        # downloaded by extract_fit_activities() after ACTIVITIES_LIST is fetched.
        if data_type.api_method_time_param == APIMethodTimeParam.PER_ACTIVITY:
            LOGGER.info(
                f"{data_type.emoji} {data_type.name} files will be handled separately "
                f"by extract_fit_activities()."
            )
            return []

        if data_type.api_method_time_param == APIMethodTimeParam.DAILY:
            # Data types whose past days can change retroactively (e.g.
            # MENSTRUAL_CYCLE_DAY) extend the start back a fixed window so those edits
            # are re-fetched and overwritten, not just the narrow incremental slice.
            effective_start = _retroactive_lookback_start(
                data_type, start_date, end_date
            )
            return self._extract_day_by_day(data_type, effective_start, end_date)

        if data_type.api_method_time_param == APIMethodTimeParam.RANGE:
            return self._extract_range(data_type, start_date, end_date)

        if data_type.api_method_time_param == APIMethodTimeParam.NO_DATE:
            # Process no-date data. Wrap the call in _with_retries so
            # transient network failures absorb the same way they do for
            # DAILY (per-day) and RANGE (per-window) types; otherwise NO_DATE
            # types (USER_PROFILE, PERSONAL_RECORDS, RACE_PREDICTIONS) would
            # fail on the first DNS hiccup.
            LOGGER.info(f"{data_type.emoji} Fetching {data_type.name.lower()} data.")
            api_method = getattr(self.garmin_client, data_type.api_method)
            data = _with_retries(api_method)

            if data:
                # Enhance USER_PROFILE data with client information.
                if data_type.name == "USER_PROFILE":
                    data["full_name"] = self.garmin_client.full_name

                return self._save_garmin_data(data, data_type, end_date)
            LOGGER.warning(f"⚠️ {data_type.emoji} {data_type.name}: No data available.")
            return []

        raise ValueError(
            f"Unsupported API method time parameter: {data_type.api_method_time_param}."
        )

    def _save_garmin_data(
        self,
        data: Union[dict, list],
        data_type: GarminDataType,
        file_date: date,
    ) -> List[Path]:
        """
        Save Garmin data to JSON file with standardized naming.

        Generates filenames with user ID, data type, and ISO 8601 timestamp for
        consistent batching. Creates midday timestamp for date-based grouping.

        :param data: The data to save. Most callers pass a dict (the typical Garmin
            response shape); per-day ACTIVITIES_LIST splits pass a list of activity
            dicts.
        :param data_type: The data type.
        :param file_date: Date for timestamp generation used in filename.
        :return: List of saved file paths.
        """
        # Create midday timestamp for consistent grouping.
        midday_datetime = datetime.combine(file_date, datetime.min.time()).replace(
            hour=12, minute=0, second=0
        )
        timestamp = pendulum.instance(midday_datetime, tz="UTC").to_iso8601_string()

        # Generate filename: {user_id}_{DATA_TYPE}_{timestamp}.json.
        filename = f"{self.user_id}_{data_type.name}_{timestamp}.json"
        filepath = self.ingest_dir / filename

        # Save data.
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        LOGGER.info(f"✅ Saved {data_type.emoji} {data_type.name}: {filename}.")
        return [filepath]

    def _load_activities_list_from_disk(self) -> Optional[list]:
        """
        Read saved ACTIVITIES_LIST JSON files in the extractor's date window from
        ``ingest_dir`` and merge them into a single deduplicated activities list.

        The registry-driven extract loop calls ``get_activities_by_date`` once for the
        full requested window inside ``_extract_range`` (RANGE-typed), then the per-day
        splitter writes one ``<user_id>_ACTIVITIES_LIST_<timestamp>.json`` file for
        every day in the window — non-empty for days with activities, an empty list
        ``[]`` for days without — so the on-disk coverage check below sees one file per
        requested day. Only files whose embedded date falls within ``[self.start_date,
        self.end_date]`` are merged: leftover files from a previous failed run with a
        different window are ignored so we don't download FIT files outside the
        requested interval. Entries are merged by ``activityId`` (last value wins for
        duplicates); entries that are not dicts or are missing ``activityId`` are
        dropped with a warning so downstream code can assume every item is a well-formed
        activity.

        Falls back to ``None`` (caller hits the live API) on any read or parse error, OR
        when the on-disk files don't cover every day in ``[start_date, end_date]`` (a
        partial run that recorded per-day failures would otherwise silently make the
        FIT-download loop skip activities for the missing days).

        :return: Merged + deduplicated activities list, or ``None`` if no in-window
            files exist, any file cannot be parsed, or the set of in-window files
            doesn't cover the full date range.
        """
        pattern = f"{self.user_id}_ACTIVITIES_LIST_*.json"
        matches = sorted(self.ingest_dir.glob(pattern))
        in_window = [m for m in matches if self._activities_list_in_window(m)]
        if not in_window:
            return None

        # Verify every day in [start_date, end_date] has a corresponding
        # ACTIVITIES_LIST file. A subset (e.g., from a partial extract that
        # had transient failures on some days) means we'd silently skip FIT
        # downloads for the missing days; force a fresh API call instead.
        expected_days = (self.end_date - self.start_date).days + 1
        seen_dates = {self._activities_list_date(m) for m in in_window}
        seen_dates.discard(None)
        if len(seen_dates) < expected_days:
            LOGGER.warning(
                f"⚠️ ACTIVITIES_LIST disk coverage incomplete for "
                f"{self.user_id} ({len(seen_dates)}/{expected_days} days "
                f"present in {self.start_date}..{self.end_date}); falling "
                f"back to API call."
            )
            return None

        merged: Dict = {}
        skipped_no_id = 0
        parsed_any = False
        for match in in_window:
            try:
                with open(match, "r", encoding="utf-8") as f:
                    payload = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                LOGGER.warning(
                    f"⚠️ Could not read {match.name}: {e}. "
                    f"Falling back to API call."
                )
                return None
            if not isinstance(payload, list):
                LOGGER.warning(
                    f"⚠️ Could not use {match.name}: expected a JSON list. "
                    f"Falling back to API call."
                )
                return None
            parsed_any = True
            for activity in payload:
                if isinstance(activity, dict) and "activityId" in activity:
                    merged[activity["activityId"]] = activity
                else:
                    skipped_no_id += 1

        if skipped_no_id:
            LOGGER.warning(
                f"⚠️ Dropped {skipped_no_id} activities-list entries without "
                f"an activityId from {self.user_id} ingest files."
            )
        # An empty list IS a valid result (the user has no activities in the
        # window). Only fall back to the API when no file was parseable.
        if not parsed_any:
            return None
        return list(merged.values())

    def _activities_list_in_window(self, path: Path) -> bool:
        """
        Return True if ``path`` is an ACTIVITIES_LIST file whose embedded date is in
        ``[self.start_date, self.end_date]``.

        :param path: Candidate ACTIVITIES_LIST file path.
        :return: True if the file's embedded date is within the window.
        """
        file_date = self._activities_list_date(path)
        if file_date is None:
            return False
        return self.start_date <= file_date <= self.end_date

    def _activities_list_date(self, path: Path) -> Optional[date]:
        """
        Parse the embedded YYYY-MM-DD date out of an ACTIVITIES_LIST filename.

        Filenames are produced by :meth:`_save_garmin_data` as
        ``<user_id>_ACTIVITIES_LIST_<ISO 8601 timestamp>.json`` where the timestamp
        begins with ``YYYY-MM-DD``. Files whose date can't be parsed are skipped with a
        warning so a malformed leftover never causes an out-of-window download or
        contributes to coverage counts.

        :param path: Candidate ACTIVITIES_LIST file path.
        :return: Parsed date, or ``None`` if the filename doesn't match the expected
            prefix or the date portion isn't a valid ISO date.
        """
        prefix = f"{self.user_id}_ACTIVITIES_LIST_"
        stem = path.stem
        if not stem.startswith(prefix):
            return None
        date_str = stem[len(prefix) : len(prefix) + 10]
        try:
            return date.fromisoformat(date_str)
        except ValueError:
            LOGGER.warning(f"⚠️ Skipping {path.name}: cannot parse date from filename.")
            return None

    def extract_fit_activities(self) -> List[Path]:
        """
        Extract FIT activity files from Garmin Connect.

        This method always processes dates inclusively - both start_date and
        end_date are included in the extraction. The extract() function handles any
        exclusion logic before passing dates to the Extractor class. Downloads binary
        FIT files with user ID, activity ID, and activity start timestamp in filename.

        :return: List of saved FIT file paths.
        """
        LOGGER.info(
            f"🏃 Fetching activities and associated FIT data from Garmin Connect "
            f"(start: {self.start_date}, end: {self.end_date} inclusive)..."
        )

        # Get list of activities. The registry-driven extract loop has
        # already fetched and saved this same data as ACTIVITIES_LIST JSON
        # in ingest_dir (the API is RANGE-typed and called once for the full
        # window, then split into per-day files). Read it from disk to avoid
        # duplicate API calls. Fall back to a live API call if the file is
        # missing or unreadable.
        start_str = self.start_date.strftime("%Y-%m-%d")
        end_str = self.end_date.strftime("%Y-%m-%d")

        activities = self._load_activities_list_from_disk()
        if activities is None:
            try:
                activities = _with_retries(
                    self.garmin_client.get_activities_by_date,
                    start_str,
                    end_str,
                )
            except Exception as e:
                LOGGER.error(
                    f"⚠️ Activity list fetch failed: {type(e).__name__}: {e}. "
                    f"No activity files will be downloaded for this account.",
                    exc_info=True,
                )
                self.failures.append(
                    ExtractionFailure(
                        user_id=self.user_id or "",
                        data_type="ACTIVITIES_LIST",
                        date=f"{start_str}..{end_str}",
                        activity_id="",
                        error=f"{type(e).__name__}: {e}",
                    )
                )
                return []

        if not activities:
            LOGGER.warning("No activities found in the specified date range.")
            return []

        LOGGER.info(f"📊 Found {len(activities)} activities.")

        downloaded_files = []

        for activity in activities:
            activity_id = activity["activityId"]

            # Generate filename with local timezone date at noon for consistent batching
            # with ACTIVITIES_LIST file. Uses same midday timestamp approach as
            # _save_garmin_data().
            activity_start = pendulum.parse(activity.get("startTimeLocal"))
            activity_date = activity_start.date()
            midday_datetime = datetime.combine(
                activity_date, datetime.min.time()
            ).replace(hour=12, minute=0, second=0)
            timestamp = pendulum.instance(midday_datetime, tz="UTC").to_iso8601_string()
            filename = f"{self.user_id}_ACTIVITY_{activity_id}_{timestamp}.fit"
            filepath = self.ingest_dir / filename

            # Download FIT file. Wrap in _with_retries for transient network
            # errors and broaden the catch to Exception so a parse error or
            # any unexpected exception on one activity does not abort the
            # whole loop.
            try:
                fit_data = _with_retries(
                    self.garmin_client.download_activity,
                    activity_id,
                    dl_fmt=self.garmin_client.ActivityDownloadFormat.ORIGINAL,
                )
            except Exception as e:
                LOGGER.warning(
                    f"⚠️ Skipping activity {activity_id}: " f"{type(e).__name__}: {e}."
                )
                self.failures.append(
                    ExtractionFailure(
                        user_id=self.user_id or "",
                        data_type="ACTIVITY",
                        date="",
                        activity_id=str(activity_id),
                        error=f"{type(e).__name__}: {e}",
                    )
                )
                continue

            # Extract FIT file from ZIP archive.
            try:
                with zipfile.ZipFile(io.BytesIO(fit_data), "r") as zip_ref:
                    # Get the first (and typically only) file from the ZIP.
                    zip_files = zip_ref.namelist()
                    if not zip_files:
                        LOGGER.warning(
                            f"⚠️ Empty ZIP archive for activity {activity_id}."
                        )
                        continue

                    # Extract the FIT file content.
                    fit_file_content = zip_ref.read(zip_files[0])
            except zipfile.BadZipFile:
                # If it's not a ZIP file, use the data as-is (fallback).
                fit_file_content = fit_data

            # Save to file.
            with open(filepath, "wb") as f:
                f.write(fit_file_content)

            file_size = filepath.stat().st_size / 1024  # KB.
            LOGGER.info(f"✅ Saved: {filename} ({file_size:.1f} KB).")
            downloaded_files.append(filepath)

            # Fetch exercise sets for strength training activities.
            activity_type_key = (
                activity.get("activityType", {}).get("typeKey", "").lower()
            )
            if activity_type_key in ("strength_training", "fitness_equipment"):
                time.sleep(0.1)  # Rate limiting between FIT and exercise sets API.
                exercise_sets_file = self._extract_exercise_sets(activity_id, timestamp)
                if exercise_sets_file:
                    downloaded_files.append(exercise_sets_file)

            # Rate limiting between activities.
            time.sleep(0.1)

        LOGGER.info(
            f"🎯 FIT activity extraction complete: {len(downloaded_files)} files saved "
            f"to {self.ingest_dir}."
        )
        return downloaded_files

    def _extract_exercise_sets(
        self, activity_id: int, timestamp: str
    ) -> Optional[Path]:
        """
        Fetch exercise sets data for a strength training activity.

        Calls the exercise sets API endpoint and saves the response as a JSON file.
        Returns None if the API returns no exercise sets data.

        :param activity_id: Garmin activity ID.
        :param timestamp: ISO 8601 timestamp for consistent filename batching.
        :return: Path to saved JSON file, or None if no data.
        """
        try:
            data = _with_retries(
                self.garmin_client.get_activity_exercise_sets, activity_id
            )
        except Exception as e:
            LOGGER.warning(
                f"⚠️ Failed to fetch exercise sets for activity {activity_id}: {e}."
            )
            return None

        # Skip if no exercise sets data.
        if not data or not data.get("exerciseSets"):
            LOGGER.info(f"💪 No exercise sets data for activity {activity_id}.")
            return None

        filename = f"{self.user_id}_EXERCISE_SETS_{activity_id}_{timestamp}.json"
        filepath = self.ingest_dir / filename

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        file_size = filepath.stat().st_size / 1024  # KB.
        LOGGER.info(f"💪 Saved: {filename} ({file_size:.1f} KB).")
        return filepath


def discover_accounts(
    base_token_dir: str = "~/.garminconnect",
) -> List[Tuple[str, Path]]:
    """
    Discover configured Garmin accounts by scanning token subdirectories.

    Each subdirectory in the base token directory represents a configured account, where
    the directory name is the Garmin user ID. Subdirectories are created by the
    refresh_garmin_tokens.py utility script during initial account setup.

    If no numeric subdirectories are found but token files exist at the root level (pre-
    multi-account layout), returns a single ``("legacy", base_path)`` entry and logs a
    migration warning.

    :param base_token_dir: Base directory containing per-account token subdirectories.
    :return: List of (user_id, token_dir_path) tuples, sorted by user_id.
    :raises FileNotFoundError: If the base token directory does not exist.
    :raises NotADirectoryError: If the base token path exists but is not a directory.
    :raises RuntimeError: If no account subdirectories and no legacy token files are
        found.
    """
    base_path = Path(base_token_dir).expanduser()

    if not base_path.exists():
        raise FileNotFoundError(
            f"Token directory {base_path} does not exist. "
            "Run refresh_garmin_tokens.py to set up at least one account."
        )

    if not base_path.is_dir():
        raise NotADirectoryError(
            f"Token path {base_path} exists but is not a directory."
        )

    # Discover accounts: each subdirectory is a user_id with tokens.
    accounts = []
    for entry in sorted(base_path.iterdir()):
        if entry.is_dir() and entry.name.isdigit():
            accounts.append((entry.name, entry))

    # Backward compatibility: if no subdirectories exist but token files are present
    # at the root level (pre-multi-account layout), treat as a single legacy account.
    if not accounts:
        token_files = list(base_path.glob("*token*.json"))
        if token_files:
            LOGGER.warning(
                f"⚠️ Legacy token layout detected in {base_path}. "
                "Tokens are at the root level instead of a user-specific subdirectory. "
                "Run refresh_garmin_tokens.py to migrate to the new layout: "
                "~/.garminconnect/<user_id>/."
            )
            return [("legacy", base_path)]

        raise RuntimeError(
            f"No account directories found in {base_path}. "
            "Run refresh_garmin_tokens.py to set up at least one account. "
            "Expected subdirectories named by Garmin user ID (e.g., 12345678/)."
        )

    LOGGER.info(
        f"🔍 Discovered {len(accounts)} Garmin account(s): "
        f"{[uid for uid, _ in accounts]}."
    )
    return accounts


def _extract_account(
    extractor: GarminExtractor,
    token_dir: Path,
    data_types: Optional[List[str]],
) -> Tuple[List[Path], List[Path]]:
    """
    Run extraction for a single Garmin account.

    Authenticates with the account's token directory and extracts all requested data
    types, including FIT activity files.

    :param extractor: Initialized GarminExtractor instance.
    :param token_dir: Path to the account's token directory.
    :param data_types: Optional list of data type names to extract.
    :return: Tuple of (garmin_files, activity_files).
    """
    extractor.authenticate(token_store_dir=str(token_dir))

    garmin_files = extractor.extract_garmin_data()

    activity_files = []
    if data_types is None or (
        data_types and {"ACTIVITY", "EXERCISE_SETS"} & set(data_types)
    ):
        activity_files = extractor.extract_fit_activities()

    return garmin_files, activity_files


def extract(
    ingest_dir: Path,
    data_interval_start: Union[str, pendulum.DateTime],
    data_interval_end: Union[str, pendulum.DateTime],
    data_types: Optional[List[str]] = None,
    **context,
) -> None:
    """
    Download data from Garmin Connect for the specified date range.

    Files are saved with standardized naming conventions to the specified directory for downstream
    processing.

    Supports multiple Garmin Connect accounts. Accounts are discovered by scanning
    subdirectories in ~/.garminconnect/, where each subdirectory is named by the Garmin
    user ID and contains authentication tokens. The extraction loops over each discovered
    account sequentially, with error isolation (one account failing does not block others).

    Accounts and data types can be filtered via DAG run configuration:
        {"accounts": ["12345678", "87654321"], "data_types": ["SLEEP", "HEART_RATE"]}
    If "accounts" is not provided, all discovered accounts are extracted.
    If "data_types" is not provided, all available data types are extracted.

    Intended to be used as a PythonOperator callable in the `extract` Airflow task.

    Authentication uses pre-existing tokens. If authentication fails, run
    refresh_garmin_tokens.py to obtain fresh tokens.

    Date ranges:
    Extract data with end date exclusion only if the start date is different from the
    end date. This ensures that when dates differ, we use exclusive end date logic,
    but when they are the same, we process the most recent data inclusively.

    The extraction includes:
    - Garmin data (JSON format) for specified data types or all available types from the
        GarminDataRegistry when `data_types` is None.
    - FIT activity files (binary format) when `data_types` is None or contains
        "ACTIVITY" or "EXERCISE_SETS".

    :param ingest_dir: Directory path where extracted files will be saved.
    :param data_interval_start: Start date for data extraction (ISO string or datetime).
    :param data_interval_end: End date for data extraction (ISO string or datetime).
    :param data_types: Optional list of data type names to extract (e.g., ['SLEEP',
        'HRV', 'USER_PROFILE', 'ACTIVITY'], provided in constants.GarminDataRegistry).
        If None, extracts all available data types including FIT activity files.
        If empty list [], skip extraction.
    :raises AirflowFailException: If every discovered account hit an
        account-level exception (e.g. all-accounts auth failure, DNS
        outage). Marks the run as Failed so the operator is alerted and
        ``prev_data_interval_end_success`` does not advance past the
        failure window.
    :raises AirflowSkipException: If the API returned no data for any
        account in the requested window (legitimate empty interval, no
        account-level failures).
    :raises ValueError: If any requested data type names are not found in registry.
    """
    # Check if this task should be skipped via configuration.
    # Example:
    # {
    #     "task_ids_to_skip": ["extract"]
    # }
    dag_run = context.get("dag_run")
    task = context.get("task")
    if dag_run and dag_run.conf and task:
        skip_list = dag_run.conf.get("task_ids_to_skip", [])
        if task.task_id in skip_list:
            raise AirflowSkipException(f"Task {task.task_id} skipped via configuration")

    # Validate input parameters.
    if data_types is not None and len(data_types) == 0:
        error_msg = (
            "data_types is an empty list. Use None to extract all types "
            "or specify data types to extract. Extraction will be skipped."
        )
        raise AirflowSkipException(error_msg)

    # Convert datetime objects or strings to date-only for Garmin API calls.
    # This ensures the API receives dates in YYYY-MM-DD format.
    if isinstance(data_interval_start, str):
        start_date = pendulum.parse(data_interval_start).date()
    else:
        start_date = data_interval_start.date()

    if isinstance(data_interval_end, str):
        original_end_date = pendulum.parse(data_interval_end).date()
    else:
        original_end_date = data_interval_end.date()

    # Apply end_date exclusion only if the start_date is different from the
    # original_end_date.
    if original_end_date > start_date:
        end_date = original_end_date - timedelta(days=1)  # Exclusive logic.
    else:
        end_date = original_end_date  # Inclusive logic for same-day processing.

    # Discover configured accounts.
    try:
        accounts = discover_accounts()
    except (FileNotFoundError, NotADirectoryError, RuntimeError) as e:
        LOGGER.error(f"❌ Account discovery failed: {e}")
        raise

    # Apply optional account filter from DAG run configuration.
    # Example: {"accounts": ["12345678"]}
    dag_run_conf = dag_run.conf if dag_run and dag_run.conf else {}
    account_filter = dag_run_conf.get("accounts")
    if account_filter:
        if not isinstance(account_filter, (list, tuple)):
            raise ValueError(
                "DAG run config 'accounts' must be a list of account IDs, "
                f"got {type(account_filter).__name__}."
            )
        account_filter_set = set(str(a) for a in account_filter)
        accounts = [(uid, path) for uid, path in accounts if uid in account_filter_set]
        if not accounts:
            raise AirflowSkipException(
                f"No matching accounts found for filter: {account_filter}. "
                "Check that the specified user IDs have token directories in "
                "~/.garminconnect/."
            )
        LOGGER.info(
            f"🔍 Account filter applied. Extracting for: "
            f"{[uid for uid, _ in accounts]}."
        )

    # Apply optional data_types filter from DAG run configuration.
    # Example: {"data_types": ["SLEEP", "HEART_RATE", "ACTIVITY"]}
    data_types_filter = dag_run_conf.get("data_types")
    if data_types_filter is not None:
        if not isinstance(data_types_filter, (list, tuple)):
            raise ValueError(
                "DAG run config 'data_types' must be a list of data type names, "
                f"got {type(data_types_filter).__name__}."
            )
        if not data_types_filter:
            raise AirflowSkipException(
                "DAG run config 'data_types' was provided as an empty list; "
                "nothing to extract."
            )
        data_types = data_types_filter
        LOGGER.info(f"🔍 Data types filter applied: {data_types}.")

    # Extract data for each account sequentially with error isolation.
    all_garmin_files = []
    all_activity_files = []
    all_failures: List[ExtractionFailure] = []
    failed_accounts = []

    for user_id, token_dir in accounts:
        LOGGER.info(f"{'=' * 60}")
        LOGGER.info(f"📥 Extracting data for account {user_id}...")

        extractor = GarminExtractor(start_date, end_date, ingest_dir, data_types)
        try:
            garmin_files, activity_files = _extract_account(
                extractor, token_dir, data_types
            )
            all_garmin_files.extend(garmin_files)
            all_activity_files.extend(activity_files)

            LOGGER.info(
                f"✅ Account {user_id}: {len(garmin_files)} data files, "
                f"{len(activity_files)} activity files."
            )
        except Exception:
            LOGGER.error(
                f"❌ Account {user_id} failed. " "Continuing with remaining accounts.",
                exc_info=True,
            )
            failed_accounts.append(user_id)
        finally:
            # Always collect per-account ExtractionFailures so granular
            # failures (per-date / per-data-type / per-activity) appear in
            # the end-of-run summary, even if the account otherwise
            # completed successfully.
            all_failures.extend(extractor.failures)

    LOGGER.info(f"{'=' * 60}")

    # Surface granular per-date / per-data-type / per-activity failures
    # collected by the per-account extractors. Logged BEFORE the skip check so
    # a "no files extracted, but per-day failures recorded" run still shows
    # what went wrong (the AirflowSkipException below would otherwise abort
    # the task before the summary printed). Group by account first so users
    # can quickly attribute failures in multi-account runs, then by data type
    # within each account.
    if all_failures:
        by_user: Dict[str, Dict[str, List[ExtractionFailure]]] = {}
        for f in all_failures:
            by_user.setdefault(f.user_id or "(unknown)", {}).setdefault(
                f.data_type, []
            ).append(f)
        account_blocks = []
        for uid, by_type in sorted(by_user.items()):
            type_lines = []
            for dt, items in sorted(by_type.items()):
                samples = []
                for item in items[:5]:
                    label = item.date or item.activity_id or "(no context)"
                    samples.append(f"        - {label}: {item.error}")
                if len(items) > 5:
                    samples.append(f"        ... and {len(items) - 5} more.")
                type_lines.append(
                    f"     • {dt}: {len(items)} failure(s)\n" + "\n".join(samples)
                )
            account_blocks.append(f"   👤 {uid}\n" + "\n".join(type_lines))
        LOGGER.warning(
            f"⚠️ Extraction failures ({len(all_failures)} total):\n"
            + "\n".join(account_blocks)
        )

    # If every discovered account hit an account-level exception (e.g. auth
    # failure, DNS resolution error), the run should fail loudly rather than
    # masquerade as a clean Skip. AirflowSkipException would mark the run
    # Success in the UI AND advance prev_data_interval_end_success past the
    # failure window, silently losing data and breaking the resume mechanism
    # for the next manual or scheduled trigger. AirflowFailException keeps
    # the failure visible (red in the UI, callbacks fire, prev_*_success
    # does not advance) so the operator can investigate and the next
    # successful run will auto-backfill the gap.
    if failed_accounts and len(failed_accounts) == len(accounts):
        raise AirflowFailException(
            f"All {len(accounts)} Garmin account(s) failed: "
            f"{failed_accounts}. See per-account logs above for the underlying "
            "error (commonly DNS / auth / transient network)."
        )

    # Check if any data was extracted across all accounts. At this point we
    # know NOT every account failed (the all-accounts-failed branch above
    # would have raised), so reaching this with no data means the API
    # legitimately returned empty for the requested window — a true skip.
    if not all_garmin_files and not all_activity_files:
        raise AirflowSkipException(
            "No Garmin Connect data found for extraction across all accounts. "
            "Skipping downstream tasks."
        )

    # Log extraction summary.
    activity_summary = (
        "\n".join([f"      • {file.name}" for file in all_activity_files])
        if all_activity_files
        else "      (none)"
    )
    garmin_summary = (
        "\n".join([f"      • {file.name}" for file in all_garmin_files])
        if all_garmin_files
        else "      (none)"
    )
    failed_summary = (
        f"\n   ⚠️ Failed accounts: {failed_accounts}" if failed_accounts else ""
    )
    LOGGER.info(
        f"🎯 Extraction Summary:\n"
        f"   📂 Saved to: {ingest_dir}\n"
        f"   👥 Accounts processed: {len(accounts) - len(failed_accounts)}"
        f"/{len(accounts)}{failed_summary}\n"
        f"   ✅ FIT activity files (total: {len(all_activity_files)}):\n"
        f"{activity_summary}\n"
        f"   ✅ Garmin data files (total: {len(all_garmin_files)}):\n{garmin_summary}"
    )


def cli_extract(
    ingest_dir: str,
    start_date: str,
    end_date: str,
    data_types: List[str] = None,
) -> None:
    """
    CLI wrapper for extract function.

    :param ingest_dir: Directory path where extracted files will be saved.
    :param start_date: Start date for data extraction in YYYY-MM-DD format.
    :param end_date: End date for data extraction in YYYY-MM-DD format (exclusive).
    :param data_types: Optional list of data type names to extract (e.g., ['SLEEP',
        'HRV', 'USER_PROFILE', 'ACTIVITY'], provided in constants.GarminDataRegistry).
        If None, extracts all available data types including FIT activity files.
    """
    # Convert string dates to pendulum datetime objects.
    start_pendulum = pendulum.parse(start_date, tz="UTC")
    end_pendulum = pendulum.parse(end_date, tz="UTC")

    # Convert string path to Path object.
    ingest_path = Path(ingest_dir)

    # Direct call to extract function.
    extract(
        ingest_dir=ingest_path,
        data_interval_start=start_pendulum,
        data_interval_end=end_pendulum,
        data_types=data_types,
    )


if __name__ == "__main__":
    # CLI entry point for the extractor.
    # Example usage:
    # python dags/pipelines/garmin/extract.py /path/to/ingest 2025-01-01 2025-01-01
    #   --data_types="[SLEEP,HRV,ACTIVITY]" for specific data types.
    #   or
    #   --data_types="[]" to skip extraction.
    #   or don't specify --data_types at all to extract all types.

    fire.Fire(cli_extract)
