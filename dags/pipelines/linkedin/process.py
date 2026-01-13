"""
LinkedIn connection data processor for ETL pipeline.

This module implements the LinkedInProcessor class that inherits from the base Processor
class to handle processing of LinkedIn connection CSV files.
"""

import csv
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional, Set

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
            )
            connection_instances.append(connection)

        LOGGER.info(f"Parsed {len(connection_instances)} connections from CSV.")

        # Upsert connections with active_connection=True.
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
                ],
            )
            LOGGER.info(f"Upserted {len(connection_instances)} connections.")

        # Mark connections not in file as inactive.
        self._mark_inactive_connections(session, file_urls)

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

    def _mark_inactive_connections(
        self, session: Session, active_urls: Set[str]
    ) -> None:
        """
        Mark connections as inactive if they are in the database but not in the current
        file export.

        :param session: SQLAlchemy Session object.
        :param active_urls: Set of URLs present in the current CSV file.
        """

        # Query all currently active connections.
        active_db_connections = (
            session.query(Connection)
            .filter(Connection.active_connection == True)  # noqa: E712
            .all()
        )

        # Find connections to mark as inactive.
        connections_to_deactivate = []
        for conn in active_db_connections:
            if conn.url not in active_urls:
                conn.active_connection = False
                connections_to_deactivate.append(conn.url)

        if connections_to_deactivate:
            LOGGER.info(
                f"Marked {len(connections_to_deactivate)} connections as inactive."
            )
            session.flush()
