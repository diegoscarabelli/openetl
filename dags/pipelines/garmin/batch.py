"""
Custom batch function for the Garmin pipeline with multi-account support.

Groups files by (user_id, timestamp) to ensure each FileSet contains data from a single
Garmin account. This prevents files from different users with the same date from being
grouped together, which would break the processor's single-user assumption.
"""

import random
import re

import pendulum
from airflow.exceptions import AirflowSkipException

from dags.lib.etl_config import ETLConfig
from dags.lib.filesystem_utils import FileSet
from dags.lib.logging_utils import LOGGER


def batch(
    config: ETLConfig, **context: dict
) -> list[tuple[list[dict[str, list[str]]]]]:
    """
    Construct batches of file sets from the content of the 'process' directory, grouping
    by (user_id, timestamp) instead of timestamp alone.

    Garmin filenames follow the pattern: {user_id}_{DATA_TYPE}_{timestamp}.{ext}
    The user_id prefix (before the first underscore) is used as an additional grouping
    key to ensure files from different accounts are never mixed in the same FileSet.

    Intended to be used as the ``batch_callable`` in the Garmin ETLConfig.

    :param config: Configuration parameters for Airflow DAGs and pipeline tasks.
    :param context: Additional Airflow keyword arguments.
    :return: Serialized batches for XCom. Each batch is a single-element tuple containing
        a list of serialized FileSets (dicts mapping file type patterns to file paths).
    """

    if config.max_process_tasks <= 0:
        raise ValueError("`max_process_tasks` must be greater than 0.")

    if config.min_file_sets_in_batch <= 0:
        raise ValueError("`min_file_sets_in_batch` must be greater than 0.")

    file_paths = list(config.data_dirs.process.glob("*"))
    files_by_key = {}

    # Timestamp regex: YYYY-MM-DDTHH:MM:SS with optional fractional seconds and timezone.
    timestamp_regex = (
        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:[+-]\d{2}:\d{2}|Z)?"
    )

    for file_path in file_paths:
        # Extract user_id from the filename prefix (before the first underscore).
        # Must be numeric: the DB schema uses BIGINT for user_id and the processor
        # casts with int(user_id).
        filename = file_path.name
        parts = filename.split("_", 1)
        if len(parts) <= 1 or not parts[0].isdigit():
            raise ValueError(
                f"Invalid Garmin filename '{filename}': expected numeric user_id "
                "prefix before first underscore (e.g., '12345678_SLEEP_...')."
            )
        user_id = parts[0]

        # Extract timestamp from the filename.
        match = re.search(timestamp_regex, filename)
        if match:
            dt = pendulum.parse(match.group(0))
        else:
            stat = file_path.stat()
            dt = pendulum.from_timestamp(stat.st_mtime).add(
                microseconds=random.randint(0, 999999)
            )

        # Group by (user_id, timestamp) to partition files per account.
        key = (user_id, dt)
        files_by_key.setdefault(key, []).append(file_path)

    # Sort by (user_id, timestamp): groups each user's files together, then
    # chronologically within each user.
    files_by_key = {k: v for k, v in sorted(files_by_key.items())}

    # Build FileSets from grouped files.
    file_sets = []
    for key, file_paths_to_group in files_by_key.items():
        file_set = FileSet()
        for file_path in file_paths_to_group:
            for pattern in config.file_types:
                if re.search(pattern.value, file_path.name):
                    if pattern not in file_set.files:
                        file_set.files[pattern] = []
                    file_set.files[pattern].append(file_path)
                    break
        # Verify all files were matched to a file type.
        if set(file_set.file_paths) != set(file_paths_to_group):
            unmatched_files = [
                f.name for f in file_paths_to_group if f not in file_set.file_paths
            ]
            raise ValueError(
                f"Not all files for key={key} were included in the file set. "
                f"Unmatched files: {unmatched_files}."
            )
        if file_set.files:
            file_sets.append(file_set)

    if not file_sets:
        raise AirflowSkipException("No files found to process.")

    # ---------------------------------------------------------------------------------
    # Construct batches of file sets (identical logic to dag_utils.batch).
    # ---------------------------------------------------------------------------------

    num_file_sets = len(file_sets)
    batches = []
    current_index = 0

    while (
        current_index + config.min_file_sets_in_batch <= num_file_sets
        and len(batches) < config.max_process_tasks
    ):
        batch_chunk = file_sets[
            current_index : current_index + config.min_file_sets_in_batch
        ]
        batches.append(batch_chunk)
        current_index += config.min_file_sets_in_batch

    if not batches:
        batches = [file_sets]

    # Distribute remaining items round-robin.
    remaining_file_sets = file_sets[current_index:]
    for i, file_set in enumerate(remaining_file_sets):
        batch_index = i % len(batches)
        batches[batch_index].append(file_set)

    # Convert FileSet objects to serializable format for XCom compatibility.
    serializable_batches = []
    for batch_chunk in batches:
        serializable_batch = [file_set.to_serializable() for file_set in batch_chunk]
        serializable_batches.append((serializable_batch,))

    LOGGER.info(
        f"Batch results: {num_file_sets} file sets grouped into "
        f"{len(serializable_batches)} batch(es)."
    )
    return serializable_batches
