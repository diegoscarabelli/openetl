"""
Backfill garmin.sleep_level from existing SLEEP JSON files.

This utility script populates the new garmin.sleep_level table from historical SLEEP
JSON files that were ingested before the sleep_level feature was added.

It walks the Garmin store directory for SLEEP JSON files, looks up the existing
sleep_id by (user_id, calendar_date), and inserts sleepLevels rows directly. The
existing GarminProcessor pipeline is intentionally NOT used so the backfill does not
re-touch the other sleep child tables (sleep_movement, spo2, hrv, etc.) or the main
sleep row.

PREREQUISITES:
- The schema migration tighten_sleep_calendar_date.sql must already be applied so
  (user_id, calendar_date) is unique in garmin.sleep.
- The garmin.sleep_level table must already exist (created by tables.ddl).
- SQL_CREDENTIALS_DIR must be set so airflow_garmin credentials can be loaded.

USAGE:
    python backfill_sleep_level.py --store-dir /path/to/garmin/store

Idempotent: uses INSERT ... ON CONFLICT DO NOTHING on (sleep_id, start_ts), matching
the runtime processor pattern, so the script can be re-run safely.
"""

import argparse
import json
import re
import traceback
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional, Tuple

from sqlalchemy.orm import Session

from dags.lib.logging_utils import LOGGER
from dags.lib.sql_utils import get_lens_engine, upsert_model_instances
from dags.pipelines.garmin.constants import SleepStage
from dags.pipelines.garmin.sqla_models import Sleep, SleepLevel

# Filename pattern: <user_id>_SLEEP_<timestamp>.json.
SLEEP_FILENAME_RE = re.compile(r"^(?P<user_id>\d+)_SLEEP_.*\.json$")


def _parse_sleep_file(
    file_path: Path,
) -> Optional[Tuple[int, date, list[dict[str, Any]]]]:
    """
    Parse a SLEEP JSON file and extract the calendar date and sleep levels.

    :param file_path: Path to the SLEEP JSON file.
    :return: Tuple of (user_id, calendar_date, sleep_levels) if parseable, otherwise
        None.
    """

    match = SLEEP_FILENAME_RE.match(file_path.name)
    if not match:
        LOGGER.warning(f"⚠️ Skipping {file_path.name}: invalid filename pattern.")
        return None
    user_id = int(match.group("user_id"))

    with open(file_path, "r", encoding="utf-8") as f:
        sleep_data = json.load(f)

    daily_sleep_dto = sleep_data.get("dailySleepDTO") or {}
    calendar_date_str = daily_sleep_dto.get("calendarDate")
    if not calendar_date_str:
        LOGGER.warning(f"⚠️ Skipping {file_path.name}: no dailySleepDTO.calendarDate.")
        return None
    try:
        calendar_date = date.fromisoformat(calendar_date_str)
    except ValueError:
        # Treat malformed dates as a skip rather than a hard failure so one bad
        # file does not poison the entire backfill run stats.
        LOGGER.warning(
            f"⚠️ Skipping {file_path.name}: invalid dailySleepDTO.calendarDate "
            f"{calendar_date_str!r}."
        )
        return None

    sleep_levels = sleep_data.get("sleepLevels") or []
    return user_id, calendar_date, sleep_levels


def _build_sleep_level_records(sleep_id: int, sleep_levels: list) -> list:
    """
    Convert raw sleepLevels JSON entries to SleepLevel ORM instances.

    :param sleep_id: Sleep session identifier.
    :param sleep_levels: Raw sleepLevels list from the JSON file.
    :return: List of SleepLevel instances ready to be persisted.
    """

    records = []
    for level in sleep_levels:
        start_gmt_str = level.get("startGMT")
        end_gmt_str = level.get("endGMT")
        activity_level = level.get("activityLevel")
        if start_gmt_str is None or end_gmt_str is None or activity_level is None:
            continue
        try:
            stage = SleepStage(int(activity_level))
        except (ValueError, TypeError):
            # ValueError: unknown int code. TypeError: activity_level is not
            # numeric/string (malformed JSON). Both treated as skip.
            LOGGER.warning(
                f"⚠️ Unparseable sleep stage value {activity_level!r} for "
                f"sleep_id={sleep_id}; skipping interval."
            )
            continue
        records.append(
            SleepLevel(
                sleep_id=sleep_id,
                start_ts=datetime.fromisoformat(start_gmt_str).replace(
                    tzinfo=timezone.utc
                ),
                end_ts=datetime.fromisoformat(end_gmt_str).replace(tzinfo=timezone.utc),
                stage=stage.value,
                stage_label=stage.name,
            )
        )
    return records


def backfill_sleep_level(store_dir: Path) -> None:
    """
    Walk store_dir for SLEEP JSON files and backfill garmin.sleep_level.

    For each file: parse calendar_date, look up the existing sleep row by
    (user_id, calendar_date), and insert sleep_level rows from the file's
    sleepLevels array using INSERT ... ON CONFLICT DO NOTHING. Existing rows for
    the same (sleep_id, start_ts) are left in place, so the script can be re-run
    safely without deleting prior data.

    :param store_dir: Garmin store directory containing SLEEP JSON files.
    """

    sleep_files = sorted(store_dir.rglob("*_SLEEP_*.json"))
    LOGGER.info(f"🔍 Found {len(sleep_files)} SLEEP files under {store_dir}.")

    engine = get_lens_engine("airflow_garmin")

    success = 0
    skipped = 0
    failed = 0
    # Counts rows submitted to INSERT, not rows actually written: ON CONFLICT DO
    # NOTHING means existing (sleep_id, start_ts) rows are silently kept.
    processed_rows = 0

    with Session(engine) as session:
        for sleep_file in sleep_files:
            try:
                parsed = _parse_sleep_file(sleep_file)
                if parsed is None:
                    skipped += 1
                    continue
                user_id, calendar_date, sleep_levels = parsed

                if not sleep_levels:
                    LOGGER.info(
                        f"⏭ Skipping {sleep_file.name}: no sleepLevels in file."
                    )
                    skipped += 1
                    continue

                sleep = (
                    session.query(Sleep)
                    .filter_by(user_id=user_id, calendar_date=calendar_date)
                    .one_or_none()
                )
                if sleep is None:
                    LOGGER.warning(
                        f"⚠️ Skipping {sleep_file.name}: no garmin.sleep row for "
                        f"user_id={user_id}, calendar_date={calendar_date}."
                    )
                    skipped += 1
                    continue
                sleep_id = sleep.sleep_id

                records = _build_sleep_level_records(sleep_id, sleep_levels)
                if not records:
                    skipped += 1
                    LOGGER.warning(f"⚠️ {sleep_file.name}: no valid sleepLevels rows.")
                    continue

                # Use INSERT ... ON CONFLICT DO NOTHING to match the runtime
                # processor pattern. Idempotent on (sleep_id, start_ts).
                upsert_model_instances(
                    session=session,
                    model_instances=records,
                    conflict_columns=["sleep_id", "start_ts"],
                    on_conflict_update=False,
                )
                session.commit()
                processed_rows += len(records)
                success += 1
                LOGGER.info(
                    f"✅ {sleep_file.name}: processed {len(records)} levels for "
                    f"sleep_id={sleep_id}."
                )
            except Exception:
                session.rollback()
                LOGGER.error(f"❌ Failed {sleep_file.name}:\n{traceback.format_exc()}")
                failed += 1

    LOGGER.info(
        f"\n🎯 Backfill complete: {success} files processed, "
        f"{skipped} skipped, {failed} failed, {processed_rows} sleep_level rows "
        f"processed (existing rows kept via ON CONFLICT DO NOTHING)."
    )


def main() -> None:
    """
    Parse CLI arguments and run the sleep_level backfill.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--store-dir",
        required=True,
        type=Path,
        help="Garmin store directory containing SLEEP JSON files (e.g. "
        "/home/user/airflow/data/garmin/store).",
    )
    args = parser.parse_args()

    if not args.store_dir.exists():
        raise SystemExit(f"❌ Store directory does not exist: {args.store_dir}.")

    backfill_sleep_level(args.store_dir)


if __name__ == "__main__":
    main()
