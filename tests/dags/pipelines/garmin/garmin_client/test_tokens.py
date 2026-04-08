"""
Unit tests for dags.pipelines.garmin.garmin_client.tokens module.

Covers serialization, file I/O, and the directory-vs-file path resolution that
the persistence helpers perform on behalf of ``GarminClient``.
"""

import json
from pathlib import Path

import pytest

from dags.pipelines.garmin.garmin_client import tokens
from dags.pipelines.garmin.garmin_client.client import GarminClient
from dags.pipelines.garmin.garmin_client.exceptions import (
    GarminAuthenticationError,
    GarminConnectionError,
)


@pytest.fixture
def populated_client() -> GarminClient:
    """
    Build a GarminClient with all three DI fields populated.

    :return: GarminClient instance with stub token state.
    """

    client = GarminClient()
    client.di_token = "stub_access_token"
    client.di_refresh_token = "stub_refresh_token"
    client.di_client_id = "STUB_CLIENT_ID"
    return client


class TestDumps:
    """
    Tests for ``tokens.dumps``.
    """

    def test_returns_json_with_three_di_fields(
        self, populated_client: GarminClient
    ) -> None:
        """
        ``dumps`` returns a JSON string containing exactly the three DI fields in the
        format the upstream library uses.
        """

        # Act.
        serialized = tokens.dumps(populated_client)

        # Assert.
        data = json.loads(serialized)
        assert data == {
            "di_token": "stub_access_token",
            "di_refresh_token": "stub_refresh_token",
            "di_client_id": "STUB_CLIENT_ID",
        }


class TestDump:
    """
    Tests for ``tokens.dump``.
    """

    def test_writes_garmin_tokens_json_when_path_is_directory(
        self, populated_client: GarminClient, tmp_path: Path
    ) -> None:
        """
        Passing a directory path appends ``garmin_tokens.json`` automatically.
        """

        # Act.
        tokens.dump(populated_client, tmp_path)

        # Assert.
        token_file = tmp_path / "garmin_tokens.json"
        assert token_file.exists()
        data = json.loads(token_file.read_text())
        assert data["di_token"] == "stub_access_token"

    def test_writes_to_explicit_json_path(
        self, populated_client: GarminClient, tmp_path: Path
    ) -> None:
        """
        A ``.json`` path is honored as-is rather than treated as a directory.
        """

        # Arrange.
        target = tmp_path / "subdir" / "custom.json"

        # Act.
        tokens.dump(populated_client, target)

        # Assert.
        assert target.exists()
        data = json.loads(target.read_text())
        assert data["di_refresh_token"] == "stub_refresh_token"


class TestLoad:
    """
    Tests for ``tokens.load`` and ``tokens.loads``.
    """

    def test_load_round_trip(
        self, populated_client: GarminClient, tmp_path: Path
    ) -> None:
        """
        A dump-then-load cycle preserves all three DI fields.
        """

        # Arrange.
        tokens.dump(populated_client, tmp_path)
        new_client = GarminClient()

        # Act.
        tokens.load(new_client, tmp_path)

        # Assert.
        assert new_client.di_token == "stub_access_token"
        assert new_client.di_refresh_token == "stub_refresh_token"
        assert new_client.di_client_id == "STUB_CLIENT_ID"
        # ``load`` records the source path so refresh can persist back.
        assert new_client._tokenstore_path == str(tmp_path)

    def test_loads_raises_on_malformed_json(self) -> None:
        """
        A malformed JSON string raises ``GarminConnectionError``.
        """

        # Arrange.
        client = GarminClient()

        # Act & Assert.
        with pytest.raises(GarminConnectionError):
            tokens.loads(client, "{not-json")

    def test_loads_raises_when_no_token_present(self) -> None:
        """
        Valid JSON without ``di_token`` raises ``GarminAuthenticationError``.
        """

        # Arrange.
        client = GarminClient()

        # Act & Assert.
        with pytest.raises(GarminAuthenticationError):
            tokens.loads(client, "{}")

    def test_load_raises_on_missing_file(self, tmp_path: Path) -> None:
        """
        A missing file path raises ``GarminConnectionError``.
        """

        # Arrange.
        client = GarminClient()

        # Act & Assert.
        with pytest.raises(GarminConnectionError):
            tokens.load(client, tmp_path / "does_not_exist")
