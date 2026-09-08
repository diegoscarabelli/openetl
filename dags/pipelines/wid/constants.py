"""
Constants and file-type definitions for the WID data pipeline.

Defines the bulk-download URL and the file-type patterns used to group the per-country
observation and metadata CSVs (and the global countries CSV) extracted from the WID bulk
ZIP.
"""

import re

from enum import Enum

# Public URL of the WID bulk dataset ZIP. The ZIP is the single source: it is a complete
# superset of the WID REST API (all observations plus aggregate entities the API omits).
BULK_URL = "https://wid.world/bulk_download/wid_all_data.zip"


class WIDFileTypes(Enum):
    """
    File types in a WID FileSet and their corresponding regex patterns.

    The bulk ZIP yields one observation CSV and one metadata CSV per country, plus a
    single global countries CSV.
    """

    OBSERVATIONS = re.compile(r"WID_data_.*\.csv$")
    VARIABLE_METADATA = re.compile(r"WID_metadata_.*\.csv$")
    COUNTRIES = re.compile(r"WID_countries.*\.csv$")


# Export for use in ETLConfig.
WID_FILE_TYPES = WIDFileTypes
