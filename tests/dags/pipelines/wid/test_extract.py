"""
Tests for the WID extract task.

Uses a small synthetic ZIP so no network access is required.
"""

import zipfile

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from airflow.sdk.exceptions import AirflowSkipException

from dags.pipelines.wid.constants import WIDFileTypes
from dags.pipelines.wid.extract import _write_members, extract


def _make_zip(tmp_path: Path) -> Path:
    zip_path = tmp_path / "wid.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "WID_data_AA.csv",
            "country;variable;percentile;year;value;age;pop\nAA;sptincj992;p99p100;2020;0.19;992;j\n",
        )
        archive.writestr(
            "WID_metadata_AA.csv", "country;variable;age;pop\nAA;sptincj992;992;j\n"
        )
        archive.writestr(
            "WID_countries.csv",
            "alpha2;titlename;shortname;region;region2\nAA;the Aaland;Aaland;Europe;NE\n",
        )
    return zip_path


def test_write_members_groups_country_files(tmp_path: Path) -> None:
    """
    A country's data and metadata get one shared timestamp; countries gets its own.
    """
    ingest = tmp_path / "ingest"
    saved = _write_members(_make_zip(tmp_path), ingest)
    assert len(saved) == 3

    names = sorted(p.name for p in ingest.iterdir())
    data = next(n for n in names if n.startswith("WID_data_AA_"))
    meta = next(n for n in names if n.startswith("WID_metadata_AA_"))
    countries = next(n for n in names if n.startswith("WID_countries_"))

    # Data and metadata for AA share the same timestamp token.
    assert data[len("WID_data_AA_") :] == meta[len("WID_metadata_AA_") :]

    # Names match the pipeline file-type patterns.
    assert WIDFileTypes.OBSERVATIONS.value.search(data)
    assert WIDFileTypes.VARIABLE_METADATA.value.search(meta)
    assert WIDFileTypes.COUNTRIES.value.search(countries)


def test_extract_skips_via_conf() -> None:
    """
    Extract raises AirflowSkipException when its task id is in task_ids_to_skip.
    """
    dag_run = MagicMock()
    dag_run.conf = {"task_ids_to_skip": ["extract"]}
    task = MagicMock()
    task.task_id = "extract"
    with pytest.raises(AirflowSkipException):
        extract(Path("/tmp/does-not-matter"), dag_run=dag_run, task=task)
