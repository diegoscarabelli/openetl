"""
Filesystem management utilities for coordinating file processing across pipeline states.

This module provides standardized directory management and file coordination
utilities for ETL pipelines. It includes:
    - DataState enum for pipeline data states (ingest, process, store, quarantine).
    - ETLDataDirectories for standardized directory management.
    - FileSet class for coordinating file processing across different file types.
    - File type pattern matching and organization utilities.
    - Integration with ETL workflow for file state transitions.
"""

import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from dags.lib.logging_utils import LOGGER


class DataState(Enum):
    """
    Enum representing the possible states of pipeline data.
    """

    INGEST = "ingest"
    PROCESS = "process"
    QUARANTINE = "quarantine"
    STORE = "store"


@dataclass
class ETLDataDirectories:
    """
    Provides standardized directory paths within the local filesystem under
    data_pipelines/data/ for different data states associated with the pipeline.
    """

    ingest: Optional[Path] = None
    process: Optional[Path] = None
    quarantine: Optional[Path] = None
    store: Optional[Path] = None

    def set_paths(self, base_dir: str, create_dirs: bool = True) -> None:
        """
        Set up paths to data directories for each data state.

        :param base_dir: Name of the base directory where pipeline data is stored.
        :param create_dirs: Whether to create directories if they don't exist.
        """

        self.ingest = self._get_directory_path(base_dir, DataState.INGEST)
        self.process = self._get_directory_path(base_dir, DataState.PROCESS)
        self.quarantine = self._get_directory_path(base_dir, DataState.QUARANTINE)
        self.store = self._get_directory_path(base_dir, DataState.STORE)
        if create_dirs:
            self._create_directories()

    @staticmethod
    def _get_directory_path(base_dir: str, data_state: DataState) -> Path:
        """
        Get the directory path for a given data state.

        Uses DATA_DIR environment variable (set by docker-compose to the container path)
        to locate the data directory.

        :param base_dir: Name of the base pipeline data directory.
        :param data_state: Data state.
        :return: Path object for the directory.
        """

        return Path(os.environ["DATA_DIR"]) / base_dir / data_state.value

    def _create_directories(self) -> None:
        """
        Create the pipeline data directories for all data states, if they don't exist.
        """

        for directory in [self.ingest, self.process, self.quarantine, self.store]:
            if directory:
                directory.mkdir(parents=True, exist_ok=True)
                LOGGER.info(f"Ensured directory exists: {directory}.")


class DefaultFileTypes(Enum):
    """
    Default file types in a FileSet and their corresponding regex patterns.

    Create a class with same signature to define the expected file types in a FileSet,
    allowing for easy identification and processing of files based on their types.
    Multiple files can be associated with each enum in a FileSet.

    Example:
        class FileTypes(Enum):
            DATA = re.compile(r".*data.*\\.csv$")
            METADATA = re.compile(r".*metadata.*\\.json$")
            CONFIG = re.compile(r".*config.*\\.json$")
    """

    DEFAULT = re.compile(r".*")


@dataclass
class FileSet:
    """
    A group of files that are logically related and processed together as a unit.

    It provides a dictionary mapping file type enums to lists of file paths for a
    specific set of files to be processed. Multiple files of each type are supported.
    The dag_utils.batch() function contains the logic to populate instances of this
    class.
    """

    # The key of the files dictionary is the file type DefaultFileTypes.
    # (e.g., DefaultFileTypes.DATA, DefaultFileTypes.METADATA).
    # Example:
    #   {FileTypes.DATA: [Path('/path/to/data/file1.csv'),
    #                     Path('/path/to/data/file2.csv')]}.
    files: Dict[Enum, List[Path]] = field(default_factory=dict)

    @property
    def file_paths(self) -> List[Path]:
        """
        Return a flat list of file paths in the file set.
        """

        file_paths = []
        for file_list in self.files.values():
            file_paths.extend(file_list)
        return file_paths

    def get_files(self, enum: Enum) -> List[Path]:
        """
        Get all files in the file set associated with the provided file type enum.

        :param enum: File type enum (e.g., GARMIN_FILE_TYPES.SLEEP).
        :return: List of Path objects, or empty list if none found.
        """

        return self.files.get(enum, [])

    def to_serializable(self) -> Dict[str, List[str]]:
        """
        Convert FileSet to a serializable format for XCom.

        :return: Dictionary with file type names as keys and lists of string paths.
        """

        serializable = {}
        for file_type, paths in self.files.items():
            # Convert enum to string and Path objects to strings.
            key = file_type.name if hasattr(file_type, "name") else str(file_type)
            serializable[key] = [str(path) for path in paths]
        return serializable

    @classmethod
    def from_serializable(
        cls, data: Dict[str, List[str]], file_types_enum
    ) -> "FileSet":
        """
        Create FileSet from serializable format.

        :param data: Dictionary with file type names as keys and string paths.
        :param file_types_enum: The file types enum class to reconstruct keys.
        :return: FileSet instance.
        """

        file_set = cls()
        for type_name, path_strings in data.items():
            # Find the enum by name.
            try:
                file_type = getattr(file_types_enum, type_name)
                file_set.files[file_type] = [
                    Path(path_str) for path_str in path_strings
                ]
            except AttributeError:
                # Skip if file type not found.
                continue
        return file_set

    def get_total_size(self) -> int:
        """
        Get the total storage size of all existing files in the file set.

        :return: Total size in bytes.
        """

        total_size = 0
        for file_path in self.file_paths:
            if file_path.exists():
                total_size += file_path.stat().st_size
        return total_size
