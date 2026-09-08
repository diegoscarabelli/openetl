"""
Tests for the WID pipeline file-type constants.
"""

from dags.pipelines.wid.constants import WIDFileTypes

DATA = "WID_data_FR_2026-05-11T03:01:54.000082Z.csv"
META = "WID_metadata_FR_2026-05-11T03:01:54.000082Z.csv"
COUNTRIES = "WID_countries_2026-05-11T03:01:54.000000Z.csv"


def test_observations_pattern() -> None:
    """
    The OBSERVATIONS pattern matches data files and rejects metadata/countries.
    """
    assert WIDFileTypes.OBSERVATIONS.value.search(DATA)
    assert not WIDFileTypes.OBSERVATIONS.value.search(META)
    assert not WIDFileTypes.OBSERVATIONS.value.search(COUNTRIES)


def test_variable_metadata_pattern() -> None:
    """
    The VARIABLE_METADATA pattern matches metadata files and rejects data files.
    """
    assert WIDFileTypes.VARIABLE_METADATA.value.search(META)
    assert not WIDFileTypes.VARIABLE_METADATA.value.search(DATA)


def test_countries_pattern() -> None:
    """
    The COUNTRIES pattern matches the countries file and rejects data files.
    """
    assert WIDFileTypes.COUNTRIES.value.search(COUNTRIES)
    assert not WIDFileTypes.COUNTRIES.value.search(DATA)
