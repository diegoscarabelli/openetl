"""
LinkedIn connection data processor for ETL pipeline.

This module implements the LinkedInProcessor class that inherits from the base Processor
class to handle processing of LinkedIn connection CSV files.
"""

import csv
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Optional, Set

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from dags.lib.dag_utils import Processor
from dags.lib.filesystem_utils import FileSet
from dags.lib.logging_utils import LOGGER
from dags.lib.sql_utils import upsert_model_instances
from dags.pipelines.linkedin.sqla_models import Connection


class LinkedInProcessor(Processor):
    """
    Custom processor for LinkedIn connection CSV files.

    Processes LinkedIn Connections CSV exports, extracting connection data and managing
    active_connection status for connections that have been removed.
    """

    def process_file_set(self, file_set: FileSet, session: Session) -> None:
        """
        Process all files in the given file set.

        For LinkedIn, each file set should contain one Connections CSV file.
        The processor:
        1. Parses the CSV file (skipping header notes).
        2. Upserts all connections from the file with active_connection=True.
        3. Sets active_connection=False for connections in DB but not in file.

        :param file_set: FileSet containing LinkedIn CSV files to process.
        :param session: SQLAlchemy Session object.
        """
        for file_path in file_set.file_paths:
            LOGGER.info(f"Processing LinkedIn connections file: {file_path.name}.")
            self._process_connections_file(file_path, session)
            LOGGER.info(f"Successfully processed {file_path.name}.")

    def _process_connections_file(self, file_path: Path, session: Session) -> None:
        """
        Process a single LinkedIn Connections CSV file.

        The CSV format has:
        - Lines 1-2: Notes (skip these).
        - Line 3: Empty line.
        - Line 4: Column headers.
        - Lines 5+: Data rows.

        :param file_path: Path to the Connections CSV file.
        :param session: SQLAlchemy Session object.
        """
        # Extract capture date from filename (e.g., "Connections_20260110.csv").
        capture_date = self._extract_capture_date(file_path)
        if not capture_date:
            LOGGER.error(f"Could not extract capture date from {file_path.name}.")
            return

        LOGGER.info(f"Processing file with capture_date: {capture_date}.")

        # Parse the CSV file and extract connections.
        connections_data = self._parse_csv_file(file_path)

        if not connections_data:
            LOGGER.warning(f"No connections found in {file_path.name}.")
            return

        # Track URLs from this file for active_connection management.
        file_urls: Set[str] = set()

        # Create Connection model instances.
        connection_instances: List[Connection] = []

        for row in connections_data:
            url = row.get("URL", "").strip()
            if not url:
                LOGGER.warning("Skipping row with empty URL.")
                continue

            file_urls.add(url)

            # Parse the connected_on date.
            connected_on = self._parse_date(row.get("Connected On", ""))

            connection = Connection(
                url=url,
                first_name=row.get("First Name", "").strip() or None,
                last_name=row.get("Last Name", "").strip() or None,
                email_address=row.get("Email Address", "").strip() or None,
                company=row.get("Company", "").strip() or None,
                position=row.get("Position", "").strip() or None,
                connected_on=connected_on,
                active_connection=True,
                capture_date=capture_date,
            )
            connection_instances.append(connection)

        LOGGER.info(f"Parsed {len(connection_instances)} connections from CSV.")

        # Upsert connections with active_connection=True.
        # Only update if capture_date in file >= capture_date in DB (prevents stale data
        # from older exports overwriting newer data during out-of-order processing).
        if connection_instances:
            upsert_model_instances(
                session=session,
                model_instances=connection_instances,
                conflict_columns=["url"],
                on_conflict_update=True,
                update_columns=[
                    "first_name",
                    "last_name",
                    "email_address",
                    "company",
                    "position",
                    "connected_on",
                    "active_connection",
                    "capture_date",
                ],
                latest_check_column="capture_date",
                latest_check_inclusive=True,
            )
            LOGGER.info(f"Upserted {len(connection_instances)} connections.")

        # Mark connections not in file as inactive (only if this file is newer).
        self._mark_inactive_connections(session, file_urls, capture_date)

    def _parse_csv_file(self, file_path: Path) -> List[dict]:
        """
        Parse LinkedIn Connections CSV file, handling the header format.

        LinkedIn CSV format:
        - Lines 1-2: Notes text.
        - Line 3: Empty.
        - Line 4: Column headers.
        - Lines 5+: Data.

        :param file_path: Path to the CSV file.
        :return: List of dictionaries containing connection data.
        """
        connections = []

        with open(file_path, "r", encoding="utf-8") as f:
            # Read all lines.
            lines = f.readlines()

            # Find the header row (contains "First Name").
            header_idx = None
            for idx, line in enumerate(lines):
                if "First Name" in line and "Last Name" in line:
                    header_idx = idx
                    break

            if header_idx is None:
                LOGGER.error(f"Could not find header row in {file_path.name}.")
                return []

            # Parse CSV starting from header row.
            csv_content = "".join(lines[header_idx:])
            reader = csv.DictReader(csv_content.splitlines())

            for row in reader:
                connections.append(row)

        return connections

    def _parse_date(self, date_str: str) -> Optional[date]:
        """
        Parse LinkedIn date format "DD Mon YYYY" (e.g., "09 Jan 2026").

        :param date_str: Date string in LinkedIn format.
        :return: date object or None if parsing fails.
        """
        if not date_str or not date_str.strip():
            return None

        try:
            # LinkedIn format: "09 Jan 2026".
            parsed = datetime.strptime(date_str.strip(), "%d %b %Y")
            return parsed.date()
        except ValueError as e:
            LOGGER.warning(f"Could not parse date '{date_str}': {e}.")
            return None

    def _extract_capture_date(self, file_path: Path) -> Optional[date]:
        """
        Extract the capture date from the filename.

        Expected filename format: "Connections_YYYYMMDD.csv" (e.g., "Connections_20260110.csv").

        :param file_path: Path to the CSV file.
        :return: date object or None if extraction fails.
        """
        # Match pattern like "20260110" in filename.
        match = re.search(r"(\d{8})", file_path.name)
        if not match:
            return None

        try:
            date_str = match.group(1)
            return datetime.strptime(date_str, "%Y%m%d").date()
        except ValueError as e:
            LOGGER.warning(
                f"Could not parse capture date from '{file_path.name}': {e}."
            )
            return None

    def _mark_inactive_connections(
        self, session: Session, active_urls: Set[str], capture_date: date
    ) -> None:
        """
        Mark connections as inactive if they are in the database but not in the current
        file export, but only if the current file is newer than the connection's
        capture_date.

        :param session: SQLAlchemy Session object.
        :param active_urls: Set of URLs present in the current CSV file.
        :param capture_date: Capture date of the current file being processed.
        """
        # Query URLs of active connections with capture_date <= current file's date.
        db_active_urls = set(
            session.execute(
                select(Connection.url)
                .where(Connection.active_connection == True)  # noqa: E712
                .where(Connection.capture_date <= capture_date)
            ).scalars()
        )

        # Find URLs to deactivate (in DB but not in file).
        urls_to_deactivate = db_active_urls - active_urls

        if urls_to_deactivate:
            # Bulk UPDATE with explicit update_ts (matches _upsert_values pattern).
            session.execute(
                update(Connection)
                .where(Connection.url.in_(urls_to_deactivate))
                .values(
                    active_connection=False,
                    capture_date=capture_date,
                    update_ts=datetime.now(timezone.utc),
                )
                .execution_options(synchronize_session=False)
            )
            LOGGER.info(f"Marked {len(urls_to_deactivate)} connections as inactive.")
