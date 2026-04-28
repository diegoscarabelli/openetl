"""
Unit tests for dags.pipelines.garmin.garmin_client.client module.

Covers the GarminClient class itself: authentication state, JWT parsing, token expiry
detection, the DI OAuth2 token exchange and refresh, and the authenticated request
helper that maps HTTP error codes to typed exceptions.
"""

import base64
import json
import time
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock, patch

import pytest
import requests

from dags.pipelines.garmin.garmin_client.client import GarminClient
from dags.pipelines.garmin.garmin_client.exceptions import (
    GarminAuthenticationError,
    GarminConnectionError,
    GarminTooManyRequestsError,
)


def _make_jwt(payload: dict) -> str:
    """
    Build a fake JWT with the given payload.

    Only the payload segment matters for client tests; we set the header and signature
    segments to placeholder strings since the client never validates them.

    :param payload: Dictionary to encode as the JWT payload.
    :return: A JWT-shaped string.
    """
    header = base64.urlsafe_b64encode(b'{"alg":"none"}').rstrip(b"=").decode()
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{header}.{body}.sig"


class TestInit:
    """
    Tests for ``GarminClient.__init__`` and basic state.
    """

    def test_default_state_unauthenticated(self) -> None:
        """
        A fresh client has no token, no profile, and is not authenticated.
        """
        # Act.
        client = GarminClient()

        # Assert.
        assert client.is_authenticated is False
        assert client.di_token is None
        assert client.di_refresh_token is None
        assert client.di_client_id is None
        assert client.display_name is None
        assert client.full_name is None
        assert client._tokenstore_path is None

    def test_domain_kwarg_sets_url_bases(self) -> None:
        """
        The ``domain`` kwarg propagates to all three URL bases.
        """
        # Act.
        client = GarminClient(domain="garmin.cn")

        # Assert.
        assert client._sso == "https://sso.garmin.cn"
        assert client._connect == "https://connect.garmin.cn"
        assert client._connectapi_url == "https://connectapi.garmin.cn"


class TestApiHeaders:
    """
    Tests for ``GarminClient.get_api_headers``.
    """

    def test_raises_when_unauthenticated(self) -> None:
        """
        An unauthenticated client cannot build API headers.
        """
        # Arrange.
        client = GarminClient()

        # Act & Assert.
        with pytest.raises(GarminAuthenticationError):
            client.get_api_headers()

    def test_returns_bearer_when_authenticated(self) -> None:
        """
        When a token is held, headers carry the Bearer token.
        """
        # Arrange.
        client = GarminClient()
        client.di_token = "stub_access_token"

        # Act.
        headers = client.get_api_headers()

        # Assert.
        assert headers["Authorization"] == "Bearer stub_access_token"
        assert headers["Accept"] == "application/json"


class TestExtractClientIdFromJwt:
    """
    Tests for the static ``_extract_client_id_from_jwt`` helper.
    """

    def test_returns_client_id_from_payload(self) -> None:
        """
        A well-formed JWT yields its ``client_id`` claim.
        """
        # Arrange.
        token = _make_jwt({"client_id": "GARMIN_TEST_CID", "exp": 9999999999})

        # Act.
        client_id = GarminClient._extract_client_id_from_jwt(token)

        # Assert.
        assert client_id == "GARMIN_TEST_CID"

    def test_returns_none_for_malformed_token(self) -> None:
        """
        A malformed token (no dots) returns None rather than raising.
        """
        # Act.
        result = GarminClient._extract_client_id_from_jwt("notajwt")

        # Assert.
        assert result is None

    def test_returns_none_when_claim_absent(self) -> None:
        """
        A JWT without ``client_id`` returns None.
        """
        # Arrange.
        token = _make_jwt({"exp": 1234567890})

        # Act.
        result = GarminClient._extract_client_id_from_jwt(token)

        # Assert.
        assert result is None


class TestTokenExpiresSoon:
    """
    Tests for ``GarminClient._token_expires_soon``.
    """

    def test_returns_true_for_expired_token(self) -> None:
        """
        A token whose ``exp`` is in the past expires "soon".
        """
        # Arrange.
        client = GarminClient()
        client.di_token = _make_jwt({"exp": int(time.time()) - 100})

        # Act & Assert.
        assert client._token_expires_soon() is True

    def test_returns_true_for_token_near_expiry(self) -> None:
        """
        A token expiring within the 15-min refresh window is flagged.
        """
        # Arrange.
        client = GarminClient()
        client.di_token = _make_jwt({"exp": int(time.time()) + 60})

        # Act & Assert.
        assert client._token_expires_soon() is True

    def test_returns_false_for_fresh_token(self) -> None:
        """
        A token with an ``exp`` 24h in the future does not need refresh.
        """
        # Arrange.
        client = GarminClient()
        client.di_token = _make_jwt({"exp": int(time.time()) + 86400})

        # Act & Assert.
        assert client._token_expires_soon() is False

    def test_returns_false_when_no_token(self) -> None:
        """
        Without a token there is nothing to refresh.
        """
        # Arrange.
        client = GarminClient()
        # Act & Assert.
        assert client._token_expires_soon() is False


class TestExchangeServiceTicket:
    """
    Tests for ``GarminClient._exchange_service_ticket``.
    """

    def test_succeeds_on_first_client_id(self) -> None:
        """
        The first DI client ID succeeds and populates all three fields.
        """
        # Arrange.
        client = GarminClient()
        token = _make_jwt({"client_id": "FIRST_CID", "exp": 9999999999})
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": token,
            "refresh_token": "fresh_refresh",
        }

        with patch.object(
            GarminClient, "_http_post", return_value=mock_response
        ) as mock_post:
            # Act.
            client._exchange_service_ticket("ticket123")

            # Assert.
            assert client.di_token == token
            assert client.di_refresh_token == "fresh_refresh"
            assert client.di_client_id == "FIRST_CID"
            mock_post.assert_called_once()

    def test_falls_through_to_next_client_id_on_failure(self) -> None:
        """
        If the first client ID returns a non-OK response, the exchange tries the next
        one.

        We verify by responding "not ok" twice and OK on the third call.
        """
        # Arrange.
        client = GarminClient()
        token = _make_jwt({"client_id": "THIRD_CID", "exp": 9999999999})

        bad_response = MagicMock()
        bad_response.ok = False
        bad_response.status_code = 400
        bad_response.text = "rejected"

        good_response = MagicMock()
        good_response.ok = True
        good_response.status_code = 200
        good_response.json.return_value = {
            "access_token": token,
            "refresh_token": "fresh_refresh",
        }

        with patch.object(
            GarminClient,
            "_http_post",
            side_effect=[bad_response, bad_response, good_response],
        ) as mock_post:
            # Act.
            client._exchange_service_ticket("ticket123")

            # Assert.
            assert mock_post.call_count == 3
            assert client.di_token == token

    def test_raises_authentication_error_when_all_fail(self) -> None:
        """
        If every client ID is rejected, the exchange raises auth error.
        """
        # Arrange.
        client = GarminClient()
        bad_response = MagicMock()
        bad_response.ok = False
        bad_response.status_code = 400
        bad_response.text = "rejected"

        with patch.object(GarminClient, "_http_post", return_value=bad_response):
            # Act & Assert.
            with pytest.raises(GarminAuthenticationError):
                client._exchange_service_ticket("ticket123")

    def test_raises_too_many_requests_on_429(self) -> None:
        """
        A 429 from the DI exchange surfaces as the typed rate-limit error.
        """
        # Arrange.
        client = GarminClient()
        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.ok = False
        rate_limited.text = "rate limited"

        with patch.object(GarminClient, "_http_post", return_value=rate_limited):
            # Act & Assert.
            with pytest.raises(GarminTooManyRequestsError):
                client._exchange_service_ticket("ticket123")

    def test_wraps_transport_error_as_connection_error(self) -> None:
        """
        Transport errors (connection, timeout, SSL) on every client ID surface as a
        typed ``GarminConnectionError`` rather than leaking the underlying
        requests/curl_cffi exception.
        """
        # Arrange.
        client = GarminClient()
        transport_error = requests.ConnectionError("network down")

        with patch.object(
            GarminClient, "_http_post", side_effect=transport_error
        ) as mock_post:
            # Act & Assert.
            with pytest.raises(GarminConnectionError) as excinfo:
                client._exchange_service_ticket("ticket123")

        # Tried every client ID before giving up.
        assert mock_post.call_count == 3
        # Wrapped the original exception via ``raise ... from``.
        assert excinfo.value.__cause__ is transport_error
        assert "transport error" in str(excinfo.value)

    def test_rejects_response_missing_refresh_token(self) -> None:
        """
        A 200 response that omits ``refresh_token`` is treated as a parse failure and
        the exchange falls through to the next client ID.

        If all three responses are similarly malformed, the exchange raises
        ``GarminAuthenticationError`` rather than half-populating client state with no
        way to refresh later.
        """
        # Arrange.
        client = GarminClient()
        token = _make_jwt({"client_id": "FIRST_CID", "exp": 9999999999})
        partial_response = MagicMock()
        partial_response.ok = True
        partial_response.status_code = 200
        # Note: no ``refresh_token`` key.
        partial_response.json.return_value = {"access_token": token}

        with patch.object(
            GarminClient, "_http_post", return_value=partial_response
        ) as mock_post:
            # Act & Assert.
            with pytest.raises(GarminAuthenticationError):
                client._exchange_service_ticket("ticket123")

        # Tried every client ID before giving up; client state never half-populated.
        assert mock_post.call_count == 3
        assert client.di_token is None
        assert client.di_refresh_token is None
        assert client.di_client_id is None


class TestRefreshDiToken:
    """
    Tests for ``GarminClient._refresh_di_token``.
    """

    def test_raises_when_no_refresh_token(self) -> None:
        """
        Cannot refresh without a refresh token + client ID.
        """
        # Arrange.
        client = GarminClient()
        # Act & Assert.
        with pytest.raises(GarminAuthenticationError):
            client._refresh_di_token()

    def test_updates_all_three_fields_on_success(self) -> None:
        """
        A successful refresh updates the access + refresh + client ID.
        """
        # Arrange.
        client = GarminClient()
        client.di_refresh_token = "old_refresh"
        client.di_client_id = "GARMIN_OLD"
        new_token = _make_jwt({"client_id": "GARMIN_NEW", "exp": 9999999999})
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "access_token": new_token,
            "refresh_token": "new_refresh",
        }

        with patch.object(GarminClient, "_http_post", return_value=mock_response):
            # Act.
            client._refresh_di_token()

            # Assert.
            assert client.di_token == new_token
            assert client.di_refresh_token == "new_refresh"
            assert client.di_client_id == "GARMIN_NEW"

    def test_keeps_old_refresh_token_when_response_omits_it(self) -> None:
        """
        If the refresh response does not include a new refresh token, the existing one
        is preserved (so the chain stays alive).
        """
        # Arrange.
        client = GarminClient()
        client.di_refresh_token = "old_refresh"
        client.di_client_id = "GARMIN_OLD"
        new_token = _make_jwt({"client_id": "GARMIN_OLD", "exp": 9999999999})
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {"access_token": new_token}

        with patch.object(GarminClient, "_http_post", return_value=mock_response):
            # Act.
            client._refresh_di_token()

            # Assert.
            assert client.di_refresh_token == "old_refresh"

    def test_raises_authentication_error_on_failure(self) -> None:
        """
        A non-OK refresh response raises auth error.
        """
        # Arrange.
        client = GarminClient()
        client.di_refresh_token = "old_refresh"
        client.di_client_id = "GARMIN_OLD"
        bad_response = MagicMock()
        bad_response.ok = False
        bad_response.status_code = 401
        bad_response.text = "expired"

        with patch.object(GarminClient, "_http_post", return_value=bad_response):
            # Act & Assert.
            with pytest.raises(GarminAuthenticationError):
                client._refresh_di_token()

    def test_raises_too_many_requests_on_429(self) -> None:
        """
        A 429 from the DI token endpoint maps to GarminTooManyRequestsError so callers
        can distinguish rate limiting from auth failure.
        """
        # Arrange.
        client = GarminClient()
        client.di_refresh_token = "old_refresh"
        client.di_client_id = "GARMIN_OLD"
        rate_limited = MagicMock()
        rate_limited.ok = False
        rate_limited.status_code = 429
        rate_limited.text = "rate limited"

        with patch.object(GarminClient, "_http_post", return_value=rate_limited):
            # Act & Assert.
            with pytest.raises(GarminTooManyRequestsError):
                client._refresh_di_token()

    @pytest.mark.parametrize(
        "exc_factory",
        [
            pytest.param(
                lambda: requests.ConnectionError("network down"),
                id="requests-connection-error",
            ),
            pytest.param(
                lambda: __import__(
                    "curl_cffi.requests.exceptions", fromlist=["RequestException"]
                ).RequestException("cffi network down"),
                id="curl-cffi-request-exception",
            ),
        ],
    )
    def test_wraps_transport_exception_as_connection_error(
        self, exc_factory: Callable[[], Exception]
    ) -> None:
        """
        Network failures (timeouts, connection resets, SSL errors) raised by the HTTP
        post are wrapped as :class:`GarminConnectionError` so callers see consistent
        typed errors.

        Both ``requests.RequestException`` (the requests-only fallback path) and
        ``curl_cffi.requests.exceptions.RequestException`` (the production cffi path)
        must be caught: the two hierarchies are unrelated, so a single ``except
        requests.RequestException`` would silently leak the cffi case.
        """
        # Arrange.
        client = GarminClient()
        client.di_refresh_token = "old_refresh"
        client.di_client_id = "GARMIN_OLD"
        with patch.object(
            GarminClient,
            "_http_post",
            side_effect=exc_factory(),
        ):
            # Act & Assert.
            with pytest.raises(GarminConnectionError, match="transport error"):
                client._refresh_di_token()

    def test_wraps_non_json_response_as_connection_error(self) -> None:
        """
        If the DI token endpoint returns a 2xx with a non-JSON body (e.g., a Cloudflare
        edge HTML page), the JSON decode failure is wrapped as
        :class:`GarminConnectionError` with a short body preview.
        """
        # Arrange.
        client = GarminClient()
        client.di_refresh_token = "old_refresh"
        client.di_client_id = "GARMIN_OLD"
        bad_body = MagicMock()
        bad_body.ok = True
        bad_body.status_code = 200
        bad_body.text = "<html>edge cache page</html>"
        bad_body.json.side_effect = json.JSONDecodeError("expecting value", "", 0)

        with patch.object(GarminClient, "_http_post", return_value=bad_body):
            # Act & Assert.
            with pytest.raises(GarminConnectionError, match="non-JSON"):
                client._refresh_di_token()

    def test_raises_authentication_error_when_access_token_missing(self) -> None:
        """
        If the DI token endpoint returns a 2xx JSON payload that doesn't contain
        ``access_token``, raise a typed :class:`GarminAuthenticationError` instead of
        leaking an untyped ``KeyError``.

        A malformed refresh response is an auth-server problem, not a transport failure,
        and callers that catch auth errors should see this case.
        """
        # Arrange.
        client = GarminClient()
        client.di_refresh_token = "old_refresh"
        client.di_client_id = "GARMIN_OLD"

        bad_response = MagicMock()
        bad_response.ok = True
        bad_response.status_code = 200
        bad_response.json.return_value = {"token_type": "Bearer", "expires_in": 3600}

        with patch.object(GarminClient, "_http_post", return_value=bad_response):
            # Act & Assert.
            with pytest.raises(GarminAuthenticationError, match="malformed"):
                client._refresh_di_token()


class TestRefreshSession:
    """
    Tests for ``GarminClient._refresh_session``.
    """

    def test_persists_to_disk_when_tokenstore_path_set(self, tmp_path: Path) -> None:
        """
        After a successful in-memory refresh, the new tokens are written back to
        ``_tokenstore_path`` so the rotating chain stays alive.
        """
        # Arrange.
        client = GarminClient()
        client.di_token = "old_token"
        client.di_refresh_token = "old_refresh"
        client.di_client_id = "OLD_CID"
        client._tokenstore_path = str(tmp_path)

        new_token = _make_jwt({"client_id": "NEW_CID", "exp": 9999999999})

        def fake_refresh() -> None:
            client.di_token = new_token
            client.di_refresh_token = "new_refresh"
            client.di_client_id = "NEW_CID"

        with patch.object(client, "_refresh_di_token", side_effect=fake_refresh):
            # Act.
            client._refresh_session()

            # Assert.
            token_file = tmp_path / "garmin_tokens.json"
            assert token_file.exists()
            data = json.loads(token_file.read_text())
            assert data["di_token"] == new_token
            assert data["di_refresh_token"] == "new_refresh"

    def test_swallows_refresh_failure(self) -> None:
        """
        Refresh failures are logged but do not propagate, so a transient DI outage
        cannot crash a long-running pipeline.
        """
        # Arrange.
        client = GarminClient()
        client.di_token = "old_token"
        with patch.object(
            client, "_refresh_di_token", side_effect=Exception("network down")
        ):
            # Act (should not raise).
            client._refresh_session()

    def test_noop_when_no_token(self) -> None:
        """
        An unauthenticated client has nothing to refresh.
        """
        # Arrange.
        client = GarminClient()

        with patch.object(client, "_refresh_di_token") as mock_refresh:
            # Act.
            client._refresh_session()

            # Assert.
            mock_refresh.assert_not_called()


class TestRequest:
    """
    Tests for ``GarminClient._request``.
    """

    def _build_client_with_token(self) -> GarminClient:
        """
        Build a client with a token that won't trigger pre-refresh.
        """
        client = GarminClient()
        client.di_token = _make_jwt(
            {"client_id": "CID", "exp": int(time.time()) + 86400}
        )
        client.di_refresh_token = "refresh"
        client.di_client_id = "CID"
        return client

    def test_retries_on_401_after_refresh(self) -> None:
        """
        On HTTP 401 the client refreshes the token once and retries; the second response
        is returned to the caller.
        """
        # Arrange.
        client = self._build_client_with_token()

        unauthorized = MagicMock()
        unauthorized.status_code = 401

        ok = MagicMock()
        ok.status_code = 200

        mock_session = MagicMock()
        mock_session.request.side_effect = [unauthorized, ok]

        with patch(
            "dags.pipelines.garmin.garmin_client.client.requests.Session",
            return_value=mock_session,
        ), patch.object(client, "_refresh_session") as mock_refresh:
            # Act.
            resp = client._request("GET", "/some/path")

            # Assert.
            assert resp is ok
            assert mock_session.request.call_count == 2
            mock_refresh.assert_called_once()

    def test_raises_authentication_error_when_401_persists(self) -> None:
        """
        If the retry also returns 401 the client surfaces a typed auth error.
        """
        # Arrange.
        client = self._build_client_with_token()

        unauthorized = MagicMock()
        unauthorized.status_code = 401

        mock_session = MagicMock()
        mock_session.request.return_value = unauthorized

        with patch(
            "dags.pipelines.garmin.garmin_client.client.requests.Session",
            return_value=mock_session,
        ), patch.object(client, "_refresh_session"):
            # Act & Assert.
            with pytest.raises(GarminAuthenticationError):
                client._request("GET", "/some/path")

    def test_maps_429_to_too_many_requests(self) -> None:
        """
        HTTP 429 raises ``GarminTooManyRequestsError``.
        """
        # Arrange.
        client = self._build_client_with_token()

        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.text = "rate limited"
        mock_session = MagicMock()
        mock_session.request.return_value = rate_limited

        with patch(
            "dags.pipelines.garmin.garmin_client.client.requests.Session",
            return_value=mock_session,
        ):
            # Act & Assert.
            with pytest.raises(GarminTooManyRequestsError):
                client._request("GET", "/some/path")

    def test_maps_5xx_to_connection_error(self) -> None:
        """
        HTTP 500-class responses raise ``GarminConnectionError``.
        """
        # Arrange.
        client = self._build_client_with_token()

        server_error = MagicMock()
        server_error.status_code = 503
        server_error.json.side_effect = Exception("not json")
        server_error.text = "service unavailable"

        mock_session = MagicMock()
        mock_session.request.return_value = server_error

        with patch(
            "dags.pipelines.garmin.garmin_client.client.requests.Session",
            return_value=mock_session,
        ):
            # Act & Assert.
            with pytest.raises(GarminConnectionError):
                client._request("GET", "/some/path")

    def test_maps_request_exception_to_connection_error(self) -> None:
        """
        Transport-layer exceptions (timeouts, connection errors, SSL failures) raised by
        ``requests`` are wrapped as :class:`GarminConnectionError` so callers see
        consistent typed errors instead of bare ``RequestException`` subclasses.
        """
        # Arrange.
        client = self._build_client_with_token()

        mock_session = MagicMock()
        mock_session.request.side_effect = requests.ConnectionError("network down")
        with patch(
            "dags.pipelines.garmin.garmin_client.client.requests.Session",
            return_value=mock_session,
        ):
            # Act & Assert.
            with pytest.raises(GarminConnectionError, match="network down"):
                client._request("GET", "/some/path")

    def test_wraps_request_exception_on_401_retry(self) -> None:
        """
        If the second (post-refresh) attempt raises a transport exception, it is also
        wrapped as :class:`GarminConnectionError` and references the retry phase
        explicitly.
        """
        # Arrange.
        client = self._build_client_with_token()

        unauthorized = MagicMock()
        unauthorized.status_code = 401

        mock_session = MagicMock()
        mock_session.request.side_effect = [
            unauthorized,
            requests.Timeout("retry timed out"),
        ]

        with patch(
            "dags.pipelines.garmin.garmin_client.client.requests.Session",
            return_value=mock_session,
        ), patch.object(client, "_refresh_session"):
            # Act & Assert.
            with pytest.raises(GarminConnectionError, match="after token refresh"):
                client._request("GET", "/some/path")


class TestConnectapi:
    """
    Tests for ``GarminClient._connectapi``.
    """

    def test_returns_parsed_json_on_success(self) -> None:
        """
        A 200 response with a valid JSON body returns the parsed dict.
        """
        # Arrange.
        client = GarminClient()
        ok_resp = MagicMock()
        ok_resp.status_code = 200
        ok_resp.json.return_value = {"hello": "world"}
        with patch.object(client, "_request", return_value=ok_resp):
            # Act.
            result = client._connectapi("/some/path")

            # Assert.
            assert result == {"hello": "world"}

    def test_returns_empty_dict_on_204(self) -> None:
        """
        HTTP 204 No Content yields an empty dict so callers don't try to parse.
        """
        # Arrange.
        client = GarminClient()
        empty_resp = MagicMock()
        empty_resp.status_code = 204

        with patch.object(client, "_request", return_value=empty_resp):
            # Act.
            result = client._connectapi("/some/path")

            # Assert.
            assert result == {}

    def test_wraps_non_json_response_as_connection_error(self) -> None:
        """
        If Garmin returns HTML (or any non-JSON) with a 2xx status (e.g., a Cloudflare
        edge cache page), the JSON decode failure is wrapped as
        :class:`GarminConnectionError` with a short body preview rather than escaping as
        a bare ``JSONDecodeError``.
        """
        # Arrange.
        client = GarminClient()
        html_resp = MagicMock()
        html_resp.status_code = 200
        html_resp.text = "<html><body>Cloudflare edge page</body></html>"
        html_resp.json.side_effect = json.JSONDecodeError("expecting value", "", 0)

        with patch.object(client, "_request", return_value=html_resp):
            # Act & Assert.
            with pytest.raises(GarminConnectionError, match="Invalid JSON"):
                client._connectapi("/some/path")


class TestFromTokens:
    """
    Tests for ``GarminClient.from_tokens``.
    """

    def test_round_trip_loads_tokens_and_profile(self, tmp_path: Path) -> None:
        """
        ``from_tokens`` reads the on-disk JSON, calls ``_load_profile`` to populate the
        display name, and returns a ready client.
        """
        # Arrange.
        token_file = tmp_path / "garmin_tokens.json"
        token_file.write_text(
            json.dumps(
                {
                    "di_token": "stub_access",
                    "di_refresh_token": "stub_refresh",
                    "di_client_id": "STUB_CID",
                }
            )
        )

        with patch.object(
            GarminClient,
            "_load_profile",
            autospec=True,
        ) as mock_load_profile:

            def populate(self) -> None:
                self.display_name = "stub_user"
                self.full_name = "Stub User"

            mock_load_profile.side_effect = populate

            # Act.
            client = GarminClient.from_tokens(tmp_path)

            # Assert.
            assert client.di_token == "stub_access"
            assert client.di_refresh_token == "stub_refresh"
            assert client.di_client_id == "STUB_CID"
            assert client.display_name == "stub_user"
            assert client.full_name == "Stub User"
            mock_load_profile.assert_called_once()


class TestLoadProfile:
    """
    Tests for ``GarminClient._load_profile``.
    """

    def test_populates_display_name_and_full_name(self) -> None:
        """
        A successful profile fetch sets both name attributes.
        """
        # Arrange.
        client = GarminClient()
        client.di_token = "stub_token"
        with patch.object(
            client,
            "_connectapi",
            return_value={"displayName": "stub_user", "fullName": "Stub User"},
        ):
            # Act.
            client._load_profile()

            # Assert.
            assert client.display_name == "stub_user"
            assert client.full_name == "Stub User"

    def test_raises_when_display_name_missing(self) -> None:
        """
        A profile response without ``displayName`` raises auth error.
        """
        # Arrange.
        client = GarminClient()
        client.di_token = "stub_token"

        with patch.object(client, "_connectapi", return_value={}):
            # Act & Assert.
            with pytest.raises(GarminAuthenticationError):
                client._load_profile()


class TestResumeLogin:
    """
    Tests for ``GarminClient.resume_login``.
    """

    def test_raises_when_no_pending_mfa(self) -> None:
        """
        Calling ``resume_login`` without a prior ``login(..., return_on_mfa=True)`` that
        returned ``("needs_mfa", ...)`` raises a typed auth error rather than leaking an
        ``AttributeError`` from the strategy module.
        """
        # Arrange: a fresh client has no ``_mfa_*_session`` attribute.
        client = GarminClient()

        # Act & Assert.
        with pytest.raises(GarminAuthenticationError, match="No pending MFA challenge"):
            client.resume_login("client_state", "123456")
