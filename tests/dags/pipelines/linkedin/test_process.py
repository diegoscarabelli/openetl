"""
Unit tests for dags.pipelines.linkedin.process module.

This test suite covers:
    - LinkedInProcessor class functionality.
    - Date parsing for LinkedIn format.
    - CSV file parsing with header notes.
    - Connection upsert and inactive marking logic.
"""

import tempfile
from datetime import date, datetime
from pathlib import Path
from typing import Set
from unittest.mock import MagicMock, patch

import pytest

from dags.lib.etl_config import ETLConfig
from dags.lib.filesystem_utils import FileSet
from dags.pipelines.linkedin.constants import LinkedInFileTypes
from dags.pipelines.linkedin.process import LinkedInProcessor
from dags.pipelines.linkedin.sqla_models import Connection


# pylint: disable=protected-access
class TestLinkedInProcessor:
    """
    Test class for LinkedInProcessor functionality.
    """

    @pytest.fixture
    def temp_dir(self):
        """
        Create temporary directory for testing.

        :return: Temporary directory path.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            yield Path(temp_dir)

    @pytest.fixture
    def processor(self) -> LinkedInProcessor:
        """
        Create LinkedInProcessor instance for testing.

        :return: LinkedInProcessor instance.
        """
        mock_config = MagicMock(spec=ETLConfig)

        with patch("dags.lib.dag_utils.ETLResult"):
            return LinkedInProcessor(
                config=mock_config,
                dag_run_id="test_run_123",
                dag_start_date=datetime(2022, 1, 1),
                file_sets=[],
            )

    @pytest.fixture
    def mock_session(self) -> MagicMock:
        """
        Create mock SQLAlchemy session for testing.

        :return: Mock session.
        """
        session = MagicMock()
        session.execute.return_value.scalars.return_value = iter([])
        return session

    @pytest.fixture
    def sample_csv_content(self) -> str:
        """
        Create sample LinkedIn Connections CSV content.

        :return: Sample CSV content with header notes.
        """
        return """Notes:
"Connections are exported from LinkedIn."

First Name,Last Name,URL,Email Address,Company,Position,Connected On
John,Doe,https://www.linkedin.com/in/johndoe,john@example.com,Acme Corp,Engineer,09 Jan 2024
Jane,Smith,https://www.linkedin.com/in/janesmith,,Tech Inc,Manager,15 Feb 2024
Bob,Wilson,https://www.linkedin.com/in/bobwilson,bob@test.com,Startup LLC,Developer,
"""

    # ==========================================================================
    # Date Parsing Tests
    # ==========================================================================

    def test_parse_date_valid(self, processor: LinkedInProcessor) -> None:
        """
        Test parsing valid LinkedIn date format.
        """
        result = processor._parse_date("09 Jan 2024")
        assert result == date(2024, 1, 9)

    def test_parse_date_various_months(self, processor: LinkedInProcessor) -> None:
        """
        Test parsing dates with various months.
        """
        test_cases = [
            ("01 Feb 2024", date(2024, 2, 1)),
            ("15 Mar 2023", date(2023, 3, 15)),
            ("25 Dec 2022", date(2022, 12, 25)),
            ("30 Apr 2021", date(2021, 4, 30)),
        ]

        for date_str, expected in test_cases:
            result = processor._parse_date(date_str)
            assert result == expected, f"Failed for {date_str}."

    def test_parse_date_empty_string(self, processor: LinkedInProcessor) -> None:
        """
        Test parsing empty date string returns None.
        """
        result = processor._parse_date("")
        assert result is None

    def test_parse_date_whitespace_only(self, processor: LinkedInProcessor) -> None:
        """
        Test parsing whitespace-only string returns None.
        """
        result = processor._parse_date("   ")
        assert result is None

    def test_parse_date_none(self, processor: LinkedInProcessor) -> None:
        """
        Test parsing None returns None.
        """
        result = processor._parse_date(None)
        assert result is None

    def test_parse_date_invalid_format(self, processor: LinkedInProcessor) -> None:
        """
        Test parsing invalid date format returns None.
        """
        result = processor._parse_date("2024-01-09")
        assert result is None

    def test_parse_date_invalid_value(self, processor: LinkedInProcessor) -> None:
        """
        Test parsing invalid date value returns None.
        """
        result = processor._parse_date("32 Jan 2024")
        assert result is None

    # ==========================================================================
    # Capture Date Extraction Tests
    # ==========================================================================

    def test_extract_capture_date_valid(self, processor: LinkedInProcessor) -> None:
        """
        Test extracting capture date from valid filename.
        """
        file_path = Path("/some/path/Connections_20240115.csv")
        result = processor._extract_capture_date(file_path)
        assert result == date(2024, 1, 15)

    def test_extract_capture_date_various_dates(
        self, processor: LinkedInProcessor
    ) -> None:
        """
        Test extracting capture dates from various filenames.
        """
        test_cases = [
            (Path("Connections_20230101.csv"), date(2023, 1, 1)),
            (Path("Connections_20241231.csv"), date(2024, 12, 31)),
            (Path("Connections_20260110.csv"), date(2026, 1, 10)),
        ]

        for file_path, expected in test_cases:
            result = processor._extract_capture_date(file_path)
            assert result == expected, f"Failed for {file_path}."

    def test_extract_capture_date_no_date_in_filename(
        self, processor: LinkedInProcessor
    ) -> None:
        """
        Test extracting capture date from filename without date returns None.
        """
        file_path = Path("Connections.csv")
        result = processor._extract_capture_date(file_path)
        assert result is None

    def test_extract_capture_date_invalid_date(
        self, processor: LinkedInProcessor
    ) -> None:
        """
        Test extracting capture date from filename with invalid date returns None.
        """
        # Invalid month (13).
        file_path = Path("Connections_20241301.csv")
        result = processor._extract_capture_date(file_path)
        assert result is None

    # ==========================================================================
    # CSV Parsing Tests
    # ==========================================================================

    def test_parse_csv_file_with_header_notes(
        self, processor: LinkedInProcessor, temp_dir: Path, sample_csv_content: str
    ) -> None:
        """
        Test parsing CSV file that includes header notes.
        """
        csv_file = temp_dir / "Connections.csv"
        csv_file.write_text(sample_csv_content)

        result = processor._parse_csv_file(csv_file)

        assert len(result) == 3
        assert result[0]["First Name"] == "John"
        assert result[0]["Last Name"] == "Doe"
        assert result[0]["URL"] == "https://www.linkedin.com/in/johndoe"
        assert result[0]["Email Address"] == "john@example.com"
        assert result[0]["Company"] == "Acme Corp"
        assert result[0]["Position"] == "Engineer"
        assert result[0]["Connected On"] == "09 Jan 2024"

    def test_parse_csv_file_empty_fields(
        self, processor: LinkedInProcessor, temp_dir: Path, sample_csv_content: str
    ) -> None:
        """
        Test parsing CSV file with empty optional fields.
        """
        csv_file = temp_dir / "Connections.csv"
        csv_file.write_text(sample_csv_content)
        result = processor._parse_csv_file(csv_file)

        # Jane Smith has no email.
        assert result[1]["Email Address"] == ""
        # Bob Wilson has no connected_on date.
        assert result[2]["Connected On"] == ""

    def test_parse_csv_file_no_header_row(
        self, processor: LinkedInProcessor, temp_dir: Path
    ) -> None:
        """
        Test parsing CSV file without valid header row returns empty list.
        """
        csv_content = """This is not a valid CSV.
Some random text.
"""

        csv_file = temp_dir / "Invalid.csv"
        csv_file.write_text(csv_content)

        result = processor._parse_csv_file(csv_file)
        assert result == []

    def test_parse_csv_file_header_at_different_line(
        self, processor: LinkedInProcessor, temp_dir: Path
    ) -> None:
        """
        Test parsing CSV file where header is at a different line number.
        """
        csv_content = """Line 1 notes.
Line 2 more notes.
Line 3 even more notes.
Line 4 still notes.

First Name,Last Name,URL,Email Address,Company,Position,Connected On
Test,User,https://www.linkedin.com/in/testuser,test@test.com,Test Co,Tester,01 Jan 2024
"""

        csv_file = temp_dir / "Connections.csv"
        csv_file.write_text(csv_content)

        result = processor._parse_csv_file(csv_file)

        assert len(result) == 1
        assert result[0]["First Name"] == "Test"

    # ==========================================================================
    # Connection Processing Tests
    # ==========================================================================

    def test_process_connections_file_creates_instances(
        self,
        processor: LinkedInProcessor,
        mock_session: MagicMock,
        temp_dir: Path,
        sample_csv_content: str,
    ) -> None:
        """
        Test that processing a CSV file creates Connection instances.
        """
        csv_file = temp_dir / "Connections_20240115.csv"
        csv_file.write_text(sample_csv_content)
        with patch(
            "dags.pipelines.linkedin.process.upsert_model_instances"
        ) as mock_upsert:
            processor._process_connections_file(csv_file, mock_session)

            # Verify upsert was called with Connection instances.
            mock_upsert.assert_called_once()
            call_kwargs = mock_upsert.call_args[1]
            instances = call_kwargs["model_instances"]

            assert len(instances) == 3
            assert all(isinstance(inst, Connection) for inst in instances)

    def test_process_connections_file_sets_active_true(
        self,
        processor: LinkedInProcessor,
        mock_session: MagicMock,
        temp_dir: Path,
        sample_csv_content: str,
    ) -> None:
        """
        Test that all processed connections have active_connection=True.
        """
        csv_file = temp_dir / "Connections_20240115.csv"
        csv_file.write_text(sample_csv_content)
        with patch(
            "dags.pipelines.linkedin.process.upsert_model_instances"
        ) as mock_upsert:
            processor._process_connections_file(csv_file, mock_session)

            instances = mock_upsert.call_args[1]["model_instances"]
            assert all(inst.active_connection is True for inst in instances)

    def test_process_connections_file_parses_dates(
        self,
        processor: LinkedInProcessor,
        mock_session: MagicMock,
        temp_dir: Path,
        sample_csv_content: str,
    ) -> None:
        """
        Test that dates are correctly parsed into date objects.
        """
        csv_file = temp_dir / "Connections_20240115.csv"
        csv_file.write_text(sample_csv_content)
        with patch(
            "dags.pipelines.linkedin.process.upsert_model_instances"
        ) as mock_upsert:
            processor._process_connections_file(csv_file, mock_session)

            instances = mock_upsert.call_args[1]["model_instances"]

            # John Doe: 09 Jan 2024.
            assert instances[0].connected_on == date(2024, 1, 9)
            # Jane Smith: 15 Feb 2024.
            assert instances[1].connected_on == date(2024, 2, 15)
            # Bob Wilson: empty date.
            assert instances[2].connected_on is None

    def test_process_connections_file_handles_empty_values(
        self,
        processor: LinkedInProcessor,
        mock_session: MagicMock,
        temp_dir: Path,
        sample_csv_content: str,
    ) -> None:
        """
        Test that empty optional fields are converted to None.
        """
        csv_file = temp_dir / "Connections_20240115.csv"
        csv_file.write_text(sample_csv_content)
        with patch(
            "dags.pipelines.linkedin.process.upsert_model_instances"
        ) as mock_upsert:
            processor._process_connections_file(csv_file, mock_session)

            instances = mock_upsert.call_args[1]["model_instances"]

            # Jane Smith has no email.
            assert instances[1].email_address is None

    def test_process_connections_file_sets_capture_date(
        self,
        processor: LinkedInProcessor,
        mock_session: MagicMock,
        temp_dir: Path,
        sample_csv_content: str,
    ) -> None:
        """
        Test that capture_date is extracted from filename and set on all connections.
        """
        csv_file = temp_dir / "Connections_20240115.csv"
        csv_file.write_text(sample_csv_content)
        with patch(
            "dags.pipelines.linkedin.process.upsert_model_instances"
        ) as mock_upsert:
            processor._process_connections_file(csv_file, mock_session)

            instances = mock_upsert.call_args[1]["model_instances"]

            # All connections should have capture_date from filename.
            expected_date = date(2024, 1, 15)
            assert all(inst.capture_date == expected_date for inst in instances)

    def test_process_connections_file_uses_latest_check_column(
        self,
        processor: LinkedInProcessor,
        mock_session: MagicMock,
        temp_dir: Path,
        sample_csv_content: str,
    ) -> None:
        """
        Test that upsert is called with latest_check_column for capture_date.
        """
        csv_file = temp_dir / "Connections_20240115.csv"
        csv_file.write_text(sample_csv_content)
        with patch(
            "dags.pipelines.linkedin.process.upsert_model_instances"
        ) as mock_upsert:
            processor._process_connections_file(csv_file, mock_session)

            call_kwargs = mock_upsert.call_args[1]
            assert call_kwargs["latest_check_column"] == "capture_date"
            assert call_kwargs["latest_check_inclusive"] is True

    def test_process_connections_file_skips_empty_url(
        self,
        processor: LinkedInProcessor,
        mock_session: MagicMock,
        temp_dir: Path,
    ) -> None:
        """
        Test that rows with empty URL are skipped.
        """
        csv_content = """Notes:
Header notes here.

First Name,Last Name,URL,Email Address,Company,Position,Connected On
John,Doe,,john@example.com,Acme Corp,Engineer,09 Jan 2024
Jane,Smith,https://www.linkedin.com/in/janesmith,,Tech Inc,Manager,15 Feb 2024
"""

        csv_file = temp_dir / "Connections_20240115.csv"
        csv_file.write_text(csv_content)
        with patch(
            "dags.pipelines.linkedin.process.upsert_model_instances"
        ) as mock_upsert:
            processor._process_connections_file(csv_file, mock_session)

            instances = mock_upsert.call_args[1]["model_instances"]
            # Only Jane Smith should be included (John has empty URL).
            assert len(instances) == 1
            assert instances[0].first_name == "Jane"

    def test_process_connections_file_empty_file(
        self,
        processor: LinkedInProcessor,
        mock_session: MagicMock,
        temp_dir: Path,
    ) -> None:
        """
        Test processing a file with no connections.
        """
        csv_content = """Notes:
Header notes here.

First Name,Last Name,URL,Email Address,Company,Position,Connected On
"""

        csv_file = temp_dir / "Connections_20240115.csv"
        csv_file.write_text(csv_content)
        with patch(
            "dags.pipelines.linkedin.process.upsert_model_instances"
        ) as mock_upsert:
            processor._process_connections_file(csv_file, mock_session)

            # Upsert should not be called with empty list.
            mock_upsert.assert_not_called()

    # ==========================================================================
    # Inactive Connection Marking Tests
    # ==========================================================================

    def test_mark_inactive_connections_deactivates_missing(
        self, processor: LinkedInProcessor, mock_session: MagicMock
    ) -> None:
        """
        Test that connections not in file are marked as inactive via bulk UPDATE.
        """
        # Track execute calls to distinguish select from update.
        execute_call_count = [0]
        scalars_mock = MagicMock()

        def execute_side_effect(stmt, *args, **kwargs):
            execute_call_count[0] += 1
            if execute_call_count[0] == 1:
                # First execute is select(Connection.url).
                return scalars_mock
            else:
                # Second execute is update(Connection).
                return MagicMock()

        mock_session.execute.side_effect = execute_side_effect

        # Mock the URL query result (scalars returns URL strings).
        scalars_mock.scalars.return_value = [
            "https://www.linkedin.com/in/existing1",
            "https://www.linkedin.com/in/existing2",
        ]

        # Only existing1 is in the current file.
        active_urls: Set[str] = {"https://www.linkedin.com/in/existing1"}
        url_to_deactivate = "https://www.linkedin.com/in/existing2"
        capture_date = date(2024, 1, 15)

        processor._mark_inactive_connections(mock_session, active_urls, capture_date)

        # Verify two execute calls: select + update.
        assert mock_session.execute.call_count == 2

        # Verify the UPDATE statement targets only the missing URL and sets
        # expected values.
        update_stmt = mock_session.execute.call_args_list[1][0][0]
        assert update_stmt.is_dml
        compiled = update_stmt.compile(compile_kwargs={"render_postcompile": True})
        compiled_str = str(compiled)
        assert "UPDATE" in compiled_str
        assert "connection" in compiled_str
        params = compiled.params
        assert params["active_connection"] is False
        assert params["capture_date"] == capture_date
        # SQLAlchemy may generate dialect-dependent key names for IN-bound URL
        # parameters, so assert by URL-related key pattern rather than one exact key.
        assert any(
            value == url_to_deactivate
            for key, value in params.items()
            if "url" in key.lower()
        )
        assert isinstance(params["update_ts"], datetime)

    def test_mark_inactive_connections_all_active(
        self, processor: LinkedInProcessor, mock_session: MagicMock
    ) -> None:
        """
        Test that no update when all DB connections are in file.
        """
        # Mock the URL query result (scalars returns URL strings).
        scalars_mock = MagicMock()
        scalars_mock.scalars.return_value = [
            "https://www.linkedin.com/in/existing",
        ]
        mock_session.execute.return_value = scalars_mock

        active_urls: Set[str] = {"https://www.linkedin.com/in/existing"}
        capture_date = date(2024, 1, 15)

        processor._mark_inactive_connections(mock_session, active_urls, capture_date)

        # Only one execute call (select). No update since all URLs are
        # in file.
        assert mock_session.execute.call_count == 1

    def test_mark_inactive_connections_empty_database(
        self, processor: LinkedInProcessor, mock_session: MagicMock
    ) -> None:
        """
        Test handling when database has no active connections.
        """
        # Mock the URL query result (scalars returns empty list).
        scalars_mock = MagicMock()
        scalars_mock.scalars.return_value = []
        mock_session.execute.return_value = scalars_mock
        active_urls: Set[str] = {"https://www.linkedin.com/in/newuser"}
        capture_date = date(2024, 1, 15)

        processor._mark_inactive_connections(mock_session, active_urls, capture_date)

        # Only one execute call (select). No update since DB is empty.
        assert mock_session.execute.call_count == 1

    # ==========================================================================
    # Process File Set Tests
    # ==========================================================================

    def test_process_file_set_calls_process_connections(
        self,
        processor: LinkedInProcessor,
        mock_session: MagicMock,
        temp_dir: Path,
        sample_csv_content: str,
    ) -> None:
        """
        Test that process_file_set processes all files in the file set.
        """
        csv_file = temp_dir / "Connections_20240115.csv"
        csv_file.write_text(sample_csv_content)

        file_set = FileSet(files={LinkedInFileTypes.CONNECTIONS: [csv_file]})

        with patch.object(processor, "_process_connections_file") as mock_process:
            processor.process_file_set(file_set, mock_session)

            mock_process.assert_called_once_with(csv_file, mock_session)

    def test_process_file_set_multiple_files(
        self,
        processor: LinkedInProcessor,
        mock_session: MagicMock,
        temp_dir: Path,
        sample_csv_content: str,
    ) -> None:
        """
        Test that process_file_set handles multiple files.
        """
        csv_file_1 = temp_dir / "Connections_20240115.csv"
        csv_file_1.write_text(sample_csv_content)

        csv_file_2 = temp_dir / "Connections_20240116.csv"
        csv_file_2.write_text(sample_csv_content)
        file_set = FileSet(
            files={LinkedInFileTypes.CONNECTIONS: [csv_file_1, csv_file_2]}
        )

        with patch.object(processor, "_process_connections_file") as mock_process:
            processor.process_file_set(file_set, mock_session)

            assert mock_process.call_count == 2
