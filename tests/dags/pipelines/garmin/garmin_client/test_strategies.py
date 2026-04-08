"""
Unit tests for dags.pipelines.garmin.garmin_client.strategies module.

Covers the five login strategies and their MFA completion functions. Each test mocks the
underlying HTTP session so no real network calls are made; the focus is on
URL/header/payload shape, the 30-45s Cloudflare-evading delay invocation, and the error
mapping for credential failures vs rate limiting.
"""

from unittest.mock import MagicMock, patch

import pytest

from dags.pipelines.garmin.garmin_client import strategies
from dags.pipelines.garmin.garmin_client.exceptions import (
    GarminAuthenticationError,
    GarminConnectionError,
    GarminTooManyRequestsError,
)


@pytest.fixture
def mock_client() -> MagicMock:
    """
    Build a minimal mock GarminClient with just the URL bases the strategies read.

    :return: MagicMock standing in for a GarminClient.
    """

    client = MagicMock()
    client._sso = "https://sso.garmin.com"
    return client


# ----------------------------------------------------------------------------------------
# WIDGET LOGIN
# ----------------------------------------------------------------------------------------


class TestWidgetLoginCffi:
    """
    Tests for ``widget_login_cffi``.
    """

    def test_raises_when_curl_cffi_unavailable(self, mock_client: MagicMock) -> None:
        """
        Without curl_cffi the widget strategy raises ``GarminConnectionError``
        immediately so the parent fallback chain advances.
        """

        with patch("dags.pipelines.garmin.garmin_client.strategies.HAS_CFFI", False):
            with pytest.raises(GarminConnectionError):
                strategies.widget_login_cffi(mock_client, "u", "p")

    def test_429_on_embed_page_raises_too_many_requests(
        self, mock_client: MagicMock
    ) -> None:
        """
        A 429 on the initial embed GET raises the typed rate-limit error.
        """

        # Arrange.
        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.ok = False

        mock_session = MagicMock()
        mock_session.get.return_value = rate_limited

        with patch(
            "dags.pipelines.garmin.garmin_client.strategies.HAS_CFFI", True
        ), patch(
            "dags.pipelines.garmin.garmin_client.strategies.cffi_requests"
        ) as mock_cffi:
            mock_cffi.Session.return_value = mock_session

            # Act & Assert.
            with pytest.raises(GarminTooManyRequestsError):
                strategies.widget_login_cffi(mock_client, "u", "p")

    def test_returns_needs_mfa_when_mfa_detected(self, mock_client: MagicMock) -> None:
        """
        When the credential POST title contains 'MFA' and ``return_on_mfa`` is True, the
        strategy stashes session state and returns the sentinel tuple.
        """

        # Arrange.
        embed_resp = MagicMock(status_code=200, ok=True, text="<html></html>")
        signin_resp = MagicMock(
            status_code=200,
            ok=True,
            url="https://sso.garmin.com/sso/signin",
            text='<input name="_csrf" value="csrf_token"/>',
        )
        post_resp = MagicMock(
            status_code=200,
            ok=True,
            text='<input name="_csrf" value="csrf_token"/><title>MFA Required</title>',
        )

        mock_session = MagicMock()
        mock_session.get.side_effect = [embed_resp, signin_resp]
        mock_session.post.return_value = post_resp

        with patch(
            "dags.pipelines.garmin.garmin_client.strategies.HAS_CFFI", True
        ), patch(
            "dags.pipelines.garmin.garmin_client.strategies.cffi_requests"
        ) as mock_cffi:
            mock_cffi.Session.return_value = mock_session

            # Act.
            result = strategies.widget_login_cffi(
                mock_client, "u", "p", return_on_mfa=True
            )

            # Assert.
            assert result[0] == "needs_mfa"
            assert hasattr(mock_client, "_widget_session")
            assert hasattr(mock_client, "_widget_signin_params")
            assert hasattr(mock_client, "_widget_last_resp")

    def test_credential_failure_raises_authentication_error(
        self, mock_client: MagicMock
    ) -> None:
        """
        A title mentioning 'invalid' triggers ``GarminAuthenticationError`` so the
        fallback chain stops trying other strategies on bad credentials.
        """

        # Arrange.
        embed_resp = MagicMock(status_code=200, ok=True, text="<html></html>")
        signin_resp = MagicMock(
            status_code=200,
            ok=True,
            url="https://sso.garmin.com/sso/signin",
            text='<input name="_csrf" value="csrf_token"/>',
        )
        post_resp = MagicMock(
            status_code=200,
            ok=True,
            text="<title>Invalid credentials</title>",
        )

        mock_session = MagicMock()
        mock_session.get.side_effect = [embed_resp, signin_resp]
        mock_session.post.return_value = post_resp

        with patch(
            "dags.pipelines.garmin.garmin_client.strategies.HAS_CFFI", True
        ), patch(
            "dags.pipelines.garmin.garmin_client.strategies.cffi_requests"
        ) as mock_cffi:
            mock_cffi.Session.return_value = mock_session

            # Act & Assert.
            with pytest.raises(GarminAuthenticationError):
                strategies.widget_login_cffi(mock_client, "u", "p")


class TestCompleteMfaWidget:
    """
    Tests for ``complete_mfa_widget``.
    """

    def test_returns_ticket_on_success(self, mock_client: MagicMock) -> None:
        """
        A successful MFA verify returns the extracted service ticket.
        """

        # Arrange.
        last_resp = MagicMock(
            text='<input name="_csrf" value="csrf_token"/>',
            url="https://sso.garmin.com/sso/signin",
        )
        verify_resp = MagicMock(
            status_code=200,
            ok=True,
            text='<title>Success</title><a href="embed?ticket=ticket123">go</a>',
        )

        mock_session = MagicMock()
        mock_session.post.return_value = verify_resp
        mock_client._widget_session = mock_session
        mock_client._widget_last_resp = last_resp
        mock_client._widget_signin_params = {}

        # Act.
        ticket = strategies.complete_mfa_widget(mock_client, "123456")

        # Assert.
        assert ticket == "ticket123"
        # Hit the verify endpoint.
        post_url = mock_session.post.call_args[0][0]
        assert post_url == "https://sso.garmin.com/sso/verifyMFA/loginEnterMfaCode"

    def test_failure_raises_authentication_error(self, mock_client: MagicMock) -> None:
        """
        A non-success title raises ``GarminAuthenticationError``.
        """

        # Arrange.
        last_resp = MagicMock(
            text='<input name="_csrf" value="csrf_token"/>',
            url="https://sso.garmin.com/sso/signin",
        )
        verify_resp = MagicMock(
            status_code=200,
            ok=True,
            text='<input name="_csrf" value="csrf_token"/><title>Invalid MFA</title>',
        )

        mock_session = MagicMock()
        mock_session.post.return_value = verify_resp
        mock_client._widget_session = mock_session
        mock_client._widget_last_resp = last_resp
        mock_client._widget_signin_params = {}

        # Act & Assert.
        with pytest.raises(GarminAuthenticationError):
            strategies.complete_mfa_widget(mock_client, "000000")


# ----------------------------------------------------------------------------------------
# PORTAL WEB LOGIN (browser flow)
# ----------------------------------------------------------------------------------------


class TestPortalWebLogin:
    """
    Tests for the shared ``_portal_web_login`` implementation.
    """

    def test_sleeps_in_anti_rate_limit_window(self, mock_client: MagicMock) -> None:
        """
        The 30-45s Cloudflare-evading delay is invoked between the SSO GET and the
        credential POST.
        """

        # Arrange. Mock POST returns SUCCESSFUL so the flow short-circuits.
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {
            "responseStatus": {"type": "SUCCESSFUL"},
            "serviceTicketId": "ticket123",
        }
        mock_session = MagicMock()
        mock_session.post.return_value = post_resp

        with patch(
            "dags.pipelines.garmin.garmin_client.strategies.time.sleep"
        ) as mock_sleep, patch(
            "dags.pipelines.garmin.garmin_client.strategies.random.uniform",
            return_value=37.5,
        ) as mock_uniform:
            # Act.
            strategies._portal_web_login(mock_client, mock_session, "u", "p")

            # Assert.
            mock_uniform.assert_called_once_with(30.0, 45.0)
            mock_sleep.assert_called_once_with(37.5)
            mock_client._establish_session.assert_called_once()

    def test_429_raises_too_many_requests(self, mock_client: MagicMock) -> None:
        """
        A 429 from the credential POST raises the typed rate-limit error.
        """

        # Arrange.
        post_resp = MagicMock()
        post_resp.status_code = 429

        mock_session = MagicMock()
        mock_session.post.return_value = post_resp

        with patch("dags.pipelines.garmin.garmin_client.strategies.time.sleep"):
            # Act & Assert.
            with pytest.raises(GarminTooManyRequestsError):
                strategies._portal_web_login(mock_client, mock_session, "u", "p")

    def test_invalid_credentials_raises_authentication_error(
        self, mock_client: MagicMock
    ) -> None:
        """
        ``INVALID_USERNAME_PASSWORD`` is mapped to ``GarminAuthenticationError``.
        """

        # Arrange.
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {
            "responseStatus": {"type": "INVALID_USERNAME_PASSWORD"}
        }

        mock_session = MagicMock()
        mock_session.post.return_value = post_resp

        with patch("dags.pipelines.garmin.garmin_client.strategies.time.sleep"):
            # Act & Assert.
            with pytest.raises(GarminAuthenticationError):
                strategies._portal_web_login(mock_client, mock_session, "u", "p")

    def test_mfa_required_returns_needs_mfa(self, mock_client: MagicMock) -> None:
        """
        ``MFA_REQUIRED`` with ``return_on_mfa=True`` stashes session state and returns
        the needs_mfa sentinel.
        """

        # Arrange.
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {
            "responseStatus": {"type": "MFA_REQUIRED"},
            "customerMfaInfo": {"mfaLastMethodUsed": "email"},
        }

        mock_session = MagicMock()
        mock_session.post.return_value = post_resp

        with patch("dags.pipelines.garmin.garmin_client.strategies.time.sleep"):
            # Act.
            result = strategies._portal_web_login(
                mock_client, mock_session, "u", "p", return_on_mfa=True
            )

            # Assert.
            assert result[0] == "needs_mfa"
            assert hasattr(mock_client, "_mfa_portal_web_session")
            assert hasattr(mock_client, "_mfa_portal_web_params")
            assert hasattr(mock_client, "_mfa_portal_web_headers")


class TestPortalWebLoginCffi:
    """
    Tests for ``portal_web_login_cffi`` (the 5-impersonation wrapper).
    """

    def test_raises_when_curl_cffi_unavailable(self, mock_client: MagicMock) -> None:
        """
        Without curl_cffi the cffi variant raises ``GarminConnectionError``.
        """

        with patch("dags.pipelines.garmin.garmin_client.strategies.HAS_CFFI", False):
            with pytest.raises(GarminConnectionError):
                strategies.portal_web_login_cffi(mock_client, "u", "p")

    def test_falls_through_impersonations_until_one_succeeds(
        self, mock_client: MagicMock
    ) -> None:
        """
        If the first 4 impersonations raise transient errors, the 5th succeeds and
        returns its result.
        """

        # Arrange.
        successful_result = (None, None)
        call_count = {"n": 0}

        def fake_login(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] < 5:
                raise Exception("transient")
            return successful_result

        with patch(
            "dags.pipelines.garmin.garmin_client.strategies.HAS_CFFI", True
        ), patch("dags.pipelines.garmin.garmin_client.strategies.cffi_requests"), patch(
            "dags.pipelines.garmin.garmin_client.strategies._portal_web_login",
            side_effect=fake_login,
        ):
            # Act.
            result = strategies.portal_web_login_cffi(mock_client, "u", "p")

            # Assert.
            assert result == successful_result
            assert call_count["n"] == 5


# ----------------------------------------------------------------------------------------
# MOBILE PORTAL LOGIN (cffi)
# ----------------------------------------------------------------------------------------


class TestPortalLoginMobileCffi:
    """
    Tests for ``portal_login`` (mobile cffi flow).
    """

    def test_sleeps_in_anti_rate_limit_window(self, mock_client: MagicMock) -> None:
        """
        The mobile cffi flow now has the same 30-45s anti-rate-limit delay as the
        browser portal flow.

        Verify it is invoked between GET and POST.
        """

        # Arrange.
        post_resp = MagicMock()
        post_resp.json.return_value = {
            "responseStatus": {"type": "SUCCESSFUL"},
            "serviceTicketId": "ticket123",
        }
        post_resp.raise_for_status = MagicMock()
        mock_session = MagicMock()
        mock_session.post.return_value = post_resp

        with patch(
            "dags.pipelines.garmin.garmin_client.strategies.HAS_CFFI", True
        ), patch(
            "dags.pipelines.garmin.garmin_client.strategies.cffi_requests"
        ) as mock_cffi, patch(
            "dags.pipelines.garmin.garmin_client.strategies.time.sleep"
        ) as mock_sleep, patch(
            "dags.pipelines.garmin.garmin_client.strategies.random.uniform",
            return_value=42.0,
        ) as mock_uniform:
            mock_cffi.Session.return_value = mock_session

            # Act.
            strategies.portal_login(mock_client, "u", "p")

            # Assert.
            mock_uniform.assert_called_once_with(30.0, 45.0)
            mock_sleep.assert_called_once_with(42.0)
            mock_client._establish_session.assert_called_once()


# ----------------------------------------------------------------------------------------
# MOBILE LOGIN (plain requests fallback)
# ----------------------------------------------------------------------------------------


class TestMobileLogin:
    """
    Tests for ``mobile_login`` (plain requests last-resort fallback).
    """

    def test_sleeps_in_anti_rate_limit_window(self, mock_client: MagicMock) -> None:
        """
        The plain-requests mobile flow now has the same delay between GET and POST as
        the cffi variants.
        """

        # Arrange.
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.json.return_value = {
            "responseStatus": {"type": "SUCCESSFUL"},
            "serviceTicketId": "ticket123",
        }

        with patch(
            "dags.pipelines.garmin.garmin_client.strategies.requests.Session"
        ) as mock_session_cls, patch(
            "dags.pipelines.garmin.garmin_client.strategies.time.sleep"
        ) as mock_sleep, patch(
            "dags.pipelines.garmin.garmin_client.strategies.random.uniform",
            return_value=33.0,
        ) as mock_uniform:
            mock_session = mock_session_cls.return_value
            mock_session.post.return_value = post_resp

            # Act.
            strategies.mobile_login(mock_client, "u", "p")

            # Assert.
            mock_uniform.assert_called_once_with(30.0, 45.0)
            mock_sleep.assert_called_once_with(33.0)
            mock_client._establish_session.assert_called_once()

    def test_429_raises_too_many_requests(self, mock_client: MagicMock) -> None:
        """
        A 429 from the credential POST raises the typed rate-limit error.
        """

        # Arrange.
        post_resp = MagicMock()
        post_resp.status_code = 429

        with patch(
            "dags.pipelines.garmin.garmin_client.strategies.requests.Session"
        ) as mock_session_cls, patch(
            "dags.pipelines.garmin.garmin_client.strategies.time.sleep"
        ):
            mock_session = mock_session_cls.return_value
            mock_session.post.return_value = post_resp

            # Act & Assert.
            with pytest.raises(GarminTooManyRequestsError):
                strategies.mobile_login(mock_client, "u", "p")
