"""
Constants and file type definitions for the LinkedIn data pipeline.

Defines the file type patterns used for matching LinkedIn CSV exports.
"""

import re
from enum import Enum


class LinkedInFileTypes(Enum):
    """
    File types in a LinkedIn FileSet and their corresponding regex patterns.

    LinkedIn exports connection data as CSV files named "Connections_YYYYMMDD.csv".
    """

    CONNECTIONS = re.compile(r"Connections.*\.csv$")


# Export for use in ETLConfig
LINKEDIN_FILE_TYPES = LinkedInFileTypes
