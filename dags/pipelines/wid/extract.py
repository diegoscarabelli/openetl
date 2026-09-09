"""
WID pipeline extraction module.

Downloads the WID bulk dataset ZIP and extracts the per-country observation and metadata
CSVs, plus the global countries CSV, into the ingest directory. Each country's two files
receive the same microsecond-resolution timestamp so the framework's batch() step groups
them into one FileSet; the countries file gets its own timestamp.
"""

import http.client
import shutil
import tempfile
import time
import urllib.request
import zipfile

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List
from urllib.error import HTTPError, URLError

from airflow.sdk.exceptions import AirflowSkipException

from dags.lib.logging_utils import LOGGER
from dags.pipelines.wid.constants import BULK_URL

MAX_RETRIES = 5
DOWNLOAD_TIMEOUT = 300

# First four bytes of every ZIP archive (local file header signature).
_ZIP_MAGIC = b"PK\x03\x04"


class _CorruptDownloadError(Exception):
    """
    Raised when the downloaded payload is not a usable ZIP archive.
    """


def extract(ingest_dir: Path, **context: dict) -> None:
    """
    Airflow entry point: download the WID bulk ZIP and unpack it into the ingest dir.

    Supports skipping via DAG run config ``{"task_ids_to_skip": ["extract"]}``.

    :param ingest_dir: Directory where extracted CSV files are written.
    :param context: Airflow task context (dag_run, task, and other injected kwargs).
    """
    dag_run = context.get("dag_run")
    task = context.get("task")
    if dag_run and getattr(dag_run, "conf", None) and task:
        if task.task_id in dag_run.conf.get("task_ids_to_skip", []):
            raise AirflowSkipException(
                f"Task {task.task_id} skipped via configuration."
            )
    _extract_bulk(Path(ingest_dir))


def _extract_bulk(ingest_dir: Path) -> List[Path]:
    """
    Download the WID bulk ZIP and write its CSV members into the ingest directory.

    :param ingest_dir: Directory where extracted CSV files are written.
    :return: List of written file paths.
    """
    zip_path = _download_zip()
    try:
        saved = _write_members(zip_path, ingest_dir)
    finally:
        zip_path.unlink(missing_ok=True)
    LOGGER.info(f"WID bulk extraction complete. Wrote {len(saved)} files.")
    return saved


def _download_zip() -> Path:
    """
    Stream the WID bulk ZIP to a temporary file, with retries and integrity checks.

    After each attempt the file size is compared to the server's Content-Length (when
    present), the first four bytes must be the ZIP magic signature, and the central
    directory must parse. Any mismatch triggers a retry.

    :return: Path to the downloaded temporary ZIP file.
    :raises RuntimeError: If all retry attempts fail.
    """
    LOGGER.info(f"Downloading WID bulk ZIP from {BULK_URL}.")
    request = urllib.request.Request(BULK_URL, headers={"User-Agent": "Mozilla/5.0"})
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    tmp_path = Path(tmp.name)
    tmp.close()

    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT) as response:
                expected = response.headers.get("Content-Length")
                with open(tmp_path, "wb") as handle:
                    shutil.copyfileobj(response, handle)
            size = tmp_path.stat().st_size
            if expected is not None and expected.isdigit() and size != int(expected):
                raise _CorruptDownloadError(
                    f"size {size} != Content-Length {expected}."
                )
            with open(tmp_path, "rb") as handle:
                if handle.read(4) != _ZIP_MAGIC:
                    raise _CorruptDownloadError("missing ZIP magic bytes.")
            with zipfile.ZipFile(tmp_path) as archive:
                if not archive.infolist():
                    raise _CorruptDownloadError("ZIP archive reports zero members.")
            LOGGER.info(f"Downloaded WID bulk ZIP ({size} bytes).")
            return tmp_path
        except (
            HTTPError,
            URLError,
            TimeoutError,
            http.client.IncompleteRead,
            zipfile.BadZipFile,
            _CorruptDownloadError,
        ) as exc:
            if attempt < MAX_RETRIES - 1:
                delay = 2**attempt
                LOGGER.warning(
                    f"Download attempt {attempt + 1} failed: {exc}. "
                    f"Retrying in {delay}s."
                )
                time.sleep(delay)
            else:
                tmp_path.unlink(missing_ok=True)
                raise RuntimeError(
                    f"WID bulk download failed after {MAX_RETRIES} attempts: {exc}."
                ) from exc

    raise RuntimeError("Unexpected exit from the download retry loop.")


def _timestamp(base_ts: datetime, index: int) -> str:
    """
    Build an ISO 8601 timestamp token unique to a group index.

    The index is added as microseconds to the base timestamp, rolling into seconds as
    needed, so distinct indices always yield distinct tokens (no reliance on microsecond
    wraparound).

    :param base_ts: Base timestamp for the extraction run.
    :param index: Group index (shared by a country's data and metadata files).
    :return: ISO 8601 string parseable by the batch() timestamp regex.
    """
    return (base_ts + timedelta(microseconds=index)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _copy_member(archive: zipfile.ZipFile, member: str, dest: Path) -> Path:
    """
    Stream one ZIP member to a destination file.

    :param archive: Open ZipFile.
    :param member: Member name within the archive.
    :param dest: Destination path.
    :return: The destination path.
    """
    with archive.open(member) as source, open(dest, "wb") as out:
        shutil.copyfileobj(source, out, length=shutil.COPY_BUFSIZE)
    LOGGER.info(f"Extracted {member} -> {dest.name}.")
    return dest


def _write_members(zip_path: Path, ingest_dir: Path) -> List[Path]:
    """
    Extract the WID data, metadata, and countries CSVs into the ingest directory.

    Each country's data and metadata files share a timestamp so batch() groups them into
    one FileSet; the countries file gets its own timestamp.

    :param zip_path: Path to the downloaded ZIP file.
    :param ingest_dir: Directory where extracted CSV files are written.
    :return: List of written file paths.
    """
    ingest_dir.mkdir(parents=True, exist_ok=True)
    saved: List[Path] = []
    with zipfile.ZipFile(zip_path) as archive:
        data_members = {}
        metadata_members = {}
        countries_member = None
        for name in archive.namelist():
            base = name.rsplit("/", 1)[-1]
            if base == "WID_countries.csv":
                countries_member = name
            elif base.startswith("WID_data_") and base.endswith(".csv"):
                data_members[base[len("WID_data_") : -len(".csv")]] = name
            elif base.startswith("WID_metadata_") and base.endswith(".csv"):
                metadata_members[base[len("WID_metadata_") : -len(".csv")]] = name

        country_codes = sorted(set(data_members) | set(metadata_members))
        base_ts = datetime.now(timezone.utc)
        for index, country in enumerate(country_codes):
            token = _timestamp(base_ts, index)
            if country in data_members:
                saved.append(
                    _copy_member(
                        archive,
                        data_members[country],
                        ingest_dir / f"WID_data_{country}_{token}.csv",
                    )
                )
            if country in metadata_members:
                saved.append(
                    _copy_member(
                        archive,
                        metadata_members[country],
                        ingest_dir / f"WID_metadata_{country}_{token}.csv",
                    )
                )
        if countries_member is not None:
            token = _timestamp(base_ts, len(country_codes))
            saved.append(
                _copy_member(
                    archive,
                    countries_member,
                    ingest_dir / f"WID_countries_{token}.csv",
                )
            )
    return saved
