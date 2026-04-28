"""
Unit tests for dags.pipelines.garmin.batch module.

This test suite covers:
    - File grouping by (user_id, timestamp) key.
    - Multi-account separation (files from different users with the same timestamp).
    - Multi-timestamp grouping within a single user.
    - Combined multi-user, multi-timestamp grouping.
    - Empty process directory handling.
    - Invalid configuration parameter validation.
    - Batch chunking logic (max_process_tasks, min_file_sets_in_batch).
"""

import re
from enum import Enum
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from airflow.sdk.exceptions import AirflowSkipException

from dags.pipelines.garmin.batch import batch

# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------


class GarminFileTypes(Enum):
    """
    Minimal file type enum for testing, mirroring the dynamically created
    GarminFileTypes from the Garmin constants module.
    """

    SLEEP = re.compile(r".*_SLEEP_.*\.json$")
    HEART_RATE = re.compile(r".*_HEART_RATE_.*\.json$")
    STEPS = re.compile(r".*_STEPS_.*\.json$")
    STRESS = re.compile(r".*_STRESS_.*\.json$")


def make_config(
    process_dir: Path,
    file_types: type = GarminFileTypes,
    max_process_tasks: int = 8,
    min_file_sets_in_batch: int = 1,
) -> MagicMock:
    """
    Create a mock ETLConfig with the given process directory and settings.

    Uses a plain MagicMock (no spec) to avoid __post_init__ validation (which requires
    the DATA_DIR environment variable) while allowing arbitrary attribute assignment on
    nested objects like data_dirs.process.

    :param process_dir: Path to the temporary process directory.
    :param file_types: Enum class with file type regex patterns.
    :param max_process_tasks: Maximum number of parallel process tasks.
    :param min_file_sets_in_batch: Minimum file sets per batch.
    :return: Mock ETLConfig instance.
    """
    config = MagicMock()
    config.data_dirs.process = process_dir
    config.file_types = file_types
    config.max_process_tasks = max_process_tasks
    config.min_file_sets_in_batch = min_file_sets_in_batch
    return config


def create_garmin_file(process_dir: Path, filename: str) -> Path:
    """
    Create an empty file in the process directory with the given filename.

    :param process_dir: Path to the process directory.
    :param filename: Name of the file to create.
    :return: Path to the created file.
    """
    file_path = process_dir / filename
    file_path.touch()
    return file_path


def collect_all_filenames(serialized_batches: list) -> list[str]:
    """
    Extract all filenames from serialized batch output.

    The batch function returns: list[tuple[list[dict[str, list[str]]], ...]]
    Each batch is a tuple containing a list of serialized FileSets.

    :param serialized_batches: Output from the batch function.
    :return: Flat list of all filenames across all batches.
    """
    filenames = []
    for batch_tuple in serialized_batches:
        for serialized_file_set_list in batch_tuple:
            for serialized_file_set in serialized_file_set_list:
                for paths in serialized_file_set.values():
                    filenames.extend(Path(p).name for p in paths)
    return filenames


def count_file_sets(serialized_batches: list) -> int:
    """
    Count the total number of FileSets across all batches.

    :param serialized_batches: Output from the batch function.
    :return: Total number of FileSets.
    """
    total = 0
    for batch_tuple in serialized_batches:
        for serialized_file_set_list in batch_tuple:
            total += len(serialized_file_set_list)
    return total


# --------------------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------------------


class TestBatchGrouping:
    """
    Tests for file grouping by (user_id, timestamp).
    """

    def test_single_user_single_timestamp(self, tmp_path: Path) -> None:
        """
        Files from a single user at the same timestamp should be grouped into one
        FileSet.
        """
        # Arrange
        ts = "2025-08-07T12:00:00Z"
        create_garmin_file(tmp_path, f"12345678_SLEEP_{ts}.json")
        create_garmin_file(tmp_path, f"12345678_HEART_RATE_{ts}.json")
        create_garmin_file(tmp_path, f"12345678_STEPS_{ts}.json")
        config = make_config(tmp_path)

        # Act
        result = batch(config)

        # Assert
        assert count_file_sets(result) == 1
        filenames = collect_all_filenames(result)
        assert len(filenames) == 3
        assert set(filenames) == {
            f"12345678_SLEEP_{ts}.json",
            f"12345678_HEART_RATE_{ts}.json",
            f"12345678_STEPS_{ts}.json",
        }

    def test_two_users_same_timestamp(self, tmp_path: Path) -> None:
        """
        Files from different users at the same timestamp must be separated into distinct
        FileSets.

        This is the core behavior that differentiates the custom batch function from the
        default dag_utils.batch: grouping by (user_id, timestamp) instead of timestamp
        alone prevents cross-user contamination.
        """
        # Arrange
        ts = "2025-08-07T12:00:00Z"
        create_garmin_file(tmp_path, f"11111111_SLEEP_{ts}.json")
        create_garmin_file(tmp_path, f"11111111_HEART_RATE_{ts}.json")
        create_garmin_file(tmp_path, f"22222222_SLEEP_{ts}.json")
        create_garmin_file(tmp_path, f"22222222_HEART_RATE_{ts}.json")
        config = make_config(tmp_path)

        # Act
        result = batch(config)

        # Assert: two FileSets, one per user.
        assert count_file_sets(result) == 2

        # Verify each FileSet contains files from only one user.
        for batch_tuple in result:
            for serialized_file_set_list in batch_tuple:
                for serialized_file_set in serialized_file_set_list:
                    all_paths = []
                    for paths in serialized_file_set.values():
                        all_paths.extend(paths)
                    user_ids = {Path(p).name.split("_")[0] for p in all_paths}
                    assert (
                        len(user_ids) == 1
                    ), f"FileSet contains files from multiple users: {user_ids}"

    def test_single_user_multiple_timestamps(self, tmp_path: Path) -> None:
        """
        Files from the same user at different timestamps should be grouped into separate
        FileSets, one per timestamp.
        """
        # Arrange
        ts1 = "2025-08-07T12:00:00Z"
        ts2 = "2025-08-08T12:00:00Z"
        create_garmin_file(tmp_path, f"12345678_SLEEP_{ts1}.json")
        create_garmin_file(tmp_path, f"12345678_HEART_RATE_{ts1}.json")
        create_garmin_file(tmp_path, f"12345678_SLEEP_{ts2}.json")
        create_garmin_file(tmp_path, f"12345678_HEART_RATE_{ts2}.json")
        config = make_config(tmp_path)

        # Act
        result = batch(config)

        # Assert: two FileSets, one per timestamp.
        assert count_file_sets(result) == 2
        filenames = collect_all_filenames(result)
        assert len(filenames) == 4

    def test_two_users_multiple_timestamps(self, tmp_path: Path) -> None:
        """
        Two users with two timestamps each should produce four FileSets, one for each
        (user_id, timestamp) combination.
        """
        # Arrange
        ts1 = "2025-08-07T12:00:00Z"
        ts2 = "2025-08-08T12:00:00Z"
        for user_id in ("11111111", "22222222"):
            for ts in (ts1, ts2):
                create_garmin_file(tmp_path, f"{user_id}_SLEEP_{ts}.json")
                create_garmin_file(tmp_path, f"{user_id}_HEART_RATE_{ts}.json")
        config = make_config(tmp_path)

        # Act
        result = batch(config)

        # Assert: four FileSets, one per (user_id, timestamp).
        assert count_file_sets(result) == 4
        filenames = collect_all_filenames(result)
        assert len(filenames) == 8

        # Verify no FileSet mixes users or timestamps.
        for batch_tuple in result:
            for serialized_file_set_list in batch_tuple:
                for serialized_file_set in serialized_file_set_list:
                    all_paths = []
                    for paths in serialized_file_set.values():
                        all_paths.extend(paths)
                    user_ids = {Path(p).name.split("_")[0] for p in all_paths}
                    assert len(user_ids) == 1, f"FileSet mixes users: {user_ids}"


class TestBatchEdgeCases:
    """
    Tests for error handling and edge cases.
    """

    def test_empty_process_directory(self, tmp_path: Path) -> None:
        """
        An empty process directory should raise AirflowSkipException, signaling that
        there is no work to do for this DAG run.
        """
        # Arrange
        config = make_config(tmp_path)

        # Act / Assert
        with pytest.raises(AirflowSkipException, match="No files found to process"):
            batch(config)

    def test_invalid_max_process_tasks(self, tmp_path: Path) -> None:
        """
        max_process_tasks <= 0 should raise ValueError before any file processing.
        """
        # Arrange
        config = make_config(tmp_path, max_process_tasks=0)

        # Act / Assert
        with pytest.raises(ValueError, match="max_process_tasks"):
            batch(config)

    def test_invalid_min_file_sets_in_batch(self, tmp_path: Path) -> None:
        """
        min_file_sets_in_batch <= 0 should raise ValueError before any file processing.
        """
        # Arrange
        config = make_config(tmp_path, min_file_sets_in_batch=0)

        # Act / Assert
        with pytest.raises(ValueError, match="min_file_sets_in_batch"):
            batch(config)

    def test_unmatched_file_raises_error(self, tmp_path: Path) -> None:
        """
        A file that doesn't match any configured file type pattern should raise
        ValueError, since the batch function performs a completeness check.
        """
        # Arrange: create a file that won't match any GarminFileTypes pattern.
        create_garmin_file(tmp_path, "12345678_UNKNOWN_TYPE_2025-08-07T12:00:00Z.json")
        config = make_config(tmp_path)

        # Act / Assert
        with pytest.raises(ValueError, match="Not all files .* were included"):
            batch(config)

    def test_file_without_numeric_user_id_prefix_raises(self, tmp_path: Path) -> None:
        """
        Files whose prefix (before the first underscore) is not numeric should raise
        ValueError.

        The DB schema uses BIGINT for user_id, so non-numeric prefixes would fail
        downstream in the processor.
        """
        # Arrange: "abc" is not numeric.
        ts = "2025-08-07T12:00:00Z"
        create_garmin_file(tmp_path, f"abc_SLEEP_{ts}.json")
        config = make_config(tmp_path)

        # Act / Assert
        with pytest.raises(ValueError, match="expected numeric user_id prefix"):
            batch(config)


class TestBatchChunking:
    """
    Tests for batch chunking logic (distributing FileSets across process tasks).
    """

    def test_file_sets_split_across_batches(self, tmp_path: Path) -> None:
        """
        With max_process_tasks=2, min_file_sets_in_batch=1, and 4 FileSets (4 distinct
        timestamps), the result should be 2 batches with 2 FileSets each.
        """
        # Arrange: 4 timestamps for user 12345678.
        for day in range(7, 11):
            ts = f"2025-08-{day:02d}T12:00:00Z"
            create_garmin_file(tmp_path, f"12345678_SLEEP_{ts}.json")
        config = make_config(tmp_path, max_process_tasks=2, min_file_sets_in_batch=1)

        # Act
        result = batch(config)

        # Assert: 2 batches, each containing 2 FileSets.
        assert len(result) == 2
        file_sets_per_batch = [len(bt[0]) for bt in result]
        assert file_sets_per_batch == [2, 2]

    def test_single_batch_when_fewer_file_sets_than_max_tasks(
        self, tmp_path: Path
    ) -> None:
        """
        When the number of FileSets is less than min_file_sets_in_batch *
        max_process_tasks, all FileSets should be placed in a single batch.
        """
        # Arrange: 1 FileSet, but max_process_tasks=4.
        create_garmin_file(tmp_path, "12345678_SLEEP_2025-08-07T12:00:00Z.json")
        config = make_config(tmp_path, max_process_tasks=4, min_file_sets_in_batch=1)

        # Act
        result = batch(config)

        # Assert: 1 batch with 1 FileSet.
        assert len(result) == 1
        assert count_file_sets(result) == 1

    def test_round_robin_distribution_of_remainders(self, tmp_path: Path) -> None:
        """
        When FileSets don't divide evenly into batches, remaining FileSets should be
        distributed round-robin across the existing batches.
        """
        # Arrange: 5 timestamps, max_process_tasks=2, min_file_sets_in_batch=2.
        # First pass: 2 batches of 2 = 4 file sets consumed. 1 remainder distributed
        # round-robin into batch 0.
        for day in range(7, 12):
            ts = f"2025-08-{day:02d}T12:00:00Z"
            create_garmin_file(tmp_path, f"12345678_SLEEP_{ts}.json")
        config = make_config(tmp_path, max_process_tasks=2, min_file_sets_in_batch=2)

        # Act
        result = batch(config)

        # Assert: 2 batches. First batch gets the remainder (3 FileSets), second has 2.
        assert len(result) == 2
        total = count_file_sets(result)
        assert total == 5
        file_sets_per_batch = sorted([len(bt[0]) for bt in result])
        assert file_sets_per_batch == [2, 3]

    def test_min_file_sets_in_batch_grouping(self, tmp_path: Path) -> None:
        """
        With min_file_sets_in_batch=3 and 6 FileSets, max_process_tasks=4, we should get
        2 batches of 3 FileSets each (not 4 batches).
        """
        # Arrange: 6 distinct timestamps.
        for day in range(7, 13):
            ts = f"2025-08-{day:02d}T12:00:00Z"
            create_garmin_file(tmp_path, f"12345678_SLEEP_{ts}.json")
        config = make_config(tmp_path, max_process_tasks=4, min_file_sets_in_batch=3)

        # Act
        result = batch(config)

        # Assert: 2 batches of 3.
        assert len(result) == 2
        file_sets_per_batch = [len(bt[0]) for bt in result]
        assert file_sets_per_batch == [3, 3]

    def test_serialized_output_structure(self, tmp_path: Path) -> None:
        """
        Verify the serialized output structure matches what XCom expects:
        list of tuples, each containing a list of serialized FileSet dicts.
        """
        # Arrange
        ts = "2025-08-07T12:00:00Z"
        create_garmin_file(tmp_path, f"12345678_SLEEP_{ts}.json")
        create_garmin_file(tmp_path, f"12345678_HEART_RATE_{ts}.json")
        config = make_config(tmp_path)

        # Act
        result = batch(config)

        # Assert: structure is list[tuple[list[dict]]]
        assert isinstance(result, list)
        assert len(result) == 1
        batch_tuple = result[0]
        assert isinstance(batch_tuple, tuple)
        assert len(batch_tuple) == 1
        serialized_list = batch_tuple[0]
        assert isinstance(serialized_list, list)
        serialized_file_set = serialized_list[0]
        assert isinstance(serialized_file_set, dict)
        assert "SLEEP" in serialized_file_set
        assert "HEART_RATE" in serialized_file_set
        # Values should be lists of string paths.
        for paths in serialized_file_set.values():
            assert isinstance(paths, list)
            for p in paths:
                assert isinstance(p, str)
