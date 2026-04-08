"""
Unit tests for dags.pipelines.garmin.garmin_client.strategies module.

Covers the five login strategies and their MFA completion functions. Each test mocks the
underlying HTTP session so no real network calls are made; the focus is on
URL/header/payload shape, the 30-45s Cloudflare-evading delay invocation, and the error
mapping for credential failures vs rate limiting.
"""

import json
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

    def test_non_ok_post_raises_with_body_preview(self, mock_client: MagicMock) -> None:
        """
        A non-2xx (but not 429) POST response surfaces as ``GarminConnectionError`` with
        a sanitized body preview, matching the pattern used by the mobile portal and MFA
        flows.

        This is the Cloudflare HTML challenge path: the
        response is non-JSON HTML, so checking ``r.ok`` first gives a better
        error message than letting ``r.json()`` fail.
        """

        # Arrange.
        post_resp = MagicMock()
        post_resp.status_code = 403
        post_resp.ok = False
        post_resp.text = "<html><body>Cloudflare challenge</body></html>"
        mock_session = MagicMock()
        mock_session.post.return_value = post_resp

        with patch("dags.pipelines.garmin.garmin_client.strategies.time.sleep"):
            # Act & Assert.
            with pytest.raises(GarminConnectionError) as excinfo:
                strategies._portal_web_login(mock_client, mock_session, "u", "p")

        msg = str(excinfo.value)
        assert "HTTP 403" in msg
        assert "Cloudflare challenge" in msg

    def test_non_json_body_raises_with_body_preview(
        self, mock_client: MagicMock
    ) -> None:
        """
        A 200 response whose body is not JSON (e.g., truncated HTML) surfaces as
        ``GarminConnectionError`` with the body preview included so the failure is
        debuggable from logs.
        """

        # Arrange.
        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.ok = True
        post_resp.text = "<html>unexpected maintenance page</html>"
        post_resp.json.side_effect = json.JSONDecodeError("no json", "doc", 0)
        mock_session = MagicMock()
        mock_session.post.return_value = post_resp

        with patch("dags.pipelines.garmin.garmin_client.strategies.time.sleep"):
            # Act & Assert.
            with pytest.raises(GarminConnectionError) as excinfo:
                strategies._portal_web_login(mock_client, mock_session, "u", "p")

        msg = str(excinfo.value)
        assert "non-JSON" in msg
        assert "unexpected maintenance page" in msg


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

    def test_continues_on_429_until_one_succeeds(self, mock_client: MagicMock) -> None:
        """
        Different curl_cffi impersonations have distinct TLS fingerprints and may be
        rate-limited independently by Cloudflare.

        If the first impersonation gets 429'd, the wrapper must try the next one (rather
        than re-raising immediately).
        """

        # Arrange.
        successful_result = (None, None)
        call_count = {"n": 0}

        def fake_login(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise GarminTooManyRequestsError("first impersonation 429'd")
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
            assert call_count["n"] == 2

    def test_propagates_too_many_requests_when_all_429(
        self, mock_client: MagicMock
    ) -> None:
        """
        When every impersonation is 429'd, the typed :class:`GarminTooManyRequestsError`
        must propagate (rather than being wrapped as a generic
        ``GarminConnectionError``) so the outer ``Client.login()`` strategy chain can
        detect the all-429 case and choose the right final error to surface.
        """

        # Arrange.
        with patch(
            "dags.pipelines.garmin.garmin_client.strategies.HAS_CFFI", True
        ), patch("dags.pipelines.garmin.garmin_client.strategies.cffi_requests"), patch(
            "dags.pipelines.garmin.garmin_client.strategies._portal_web_login",
            side_effect=GarminTooManyRequestsError("rate limited"),
        ):
            # Act & Assert.
            with pytest.raises(GarminTooManyRequestsError):
                strategies.portal_web_login_cffi(mock_client, "u", "p")


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

    def test_get_429_raises_before_sleeping(self, mock_client: MagicMock) -> None:
        """
        A 429 on the initial GET raises ``GarminTooManyRequestsError`` before any delay
        is taken so we don't waste 30-45s sleeping for nothing.
        """

        # Arrange.
        get_resp = MagicMock()
        get_resp.status_code = 429
        get_resp.ok = False

        with patch(
            "dags.pipelines.garmin.garmin_client.strategies.requests.Session"
        ) as mock_session_cls, patch(
            "dags.pipelines.garmin.garmin_client.strategies.time.sleep"
        ) as mock_sleep:
            mock_session = mock_session_cls.return_value
            mock_session.get.return_value = get_resp

            # Act & Assert.
            with pytest.raises(GarminTooManyRequestsError):
                strategies.mobile_login(mock_client, "u", "p")

            # Sleep must not have been called: we bailed before the delay.
            mock_sleep.assert_not_called()
            mock_session.post.assert_not_called()

    def test_get_non_ok_raises_connection_error(self, mock_client: MagicMock) -> None:
        """
        A non-2xx (e.g., 503) on the initial GET raises ``GarminConnectionError`` before
        sleeping or attempting credentials.
        """

        # Arrange.
        get_resp = MagicMock()
        get_resp.status_code = 503
        get_resp.ok = False

        with patch(
            "dags.pipelines.garmin.garmin_client.strategies.requests.Session"
        ) as mock_session_cls, patch(
            "dags.pipelines.garmin.garmin_client.strategies.time.sleep"
        ):
            mock_session = mock_session_cls.return_value
            mock_session.get.return_value = get_resp

            # Act & Assert.
            with pytest.raises(GarminConnectionError):
                strategies.mobile_login(mock_client, "u", "p")

    def test_get_and_post_use_explicit_timeout(self, mock_client: MagicMock) -> None:
        """
        Both the sign-in GET and the credential POST forward an explicit ``timeout``
        kwarg so the calls can never hang indefinitely in long-running pipelines.
        """

        # Arrange.
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.ok = True

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
        ):
            mock_session = mock_session_cls.return_value
            mock_session.get.return_value = get_resp
            mock_session.post.return_value = post_resp

            # Act.
            strategies.mobile_login(mock_client, "u", "p")

            # Assert.
            assert "timeout" in mock_session.get.call_args.kwargs
            assert "timeout" in mock_session.post.call_args.kwargs


class TestPortalWebLoginGet:
    """
    Tests for the GET-side of ``_portal_web_login`` (Round 3 hardening).
    """

    def test_get_429_raises_before_sleeping(self, mock_client: MagicMock) -> None:
        """
        A 429 on the SSO sign-in GET raises ``GarminTooManyRequestsError`` immediately
        rather than sleeping 30-45s and then attempting a doomed credential POST.
        """

        # Arrange.
        get_resp = MagicMock()
        get_resp.status_code = 429
        get_resp.ok = False

        mock_session = MagicMock()
        mock_session.get.return_value = get_resp

        with patch(
            "dags.pipelines.garmin.garmin_client.strategies.time.sleep"
        ) as mock_sleep:
            # Act & Assert.
            with pytest.raises(GarminTooManyRequestsError):
                strategies._portal_web_login(mock_client, mock_session, "u", "p")

            # Sleep must not have been called: we bailed before the delay.
            mock_sleep.assert_not_called()
            mock_session.post.assert_not_called()

    def test_get_non_ok_raises_connection_error(self, mock_client: MagicMock) -> None:
        """
        A non-2xx (e.g., 502 Bad Gateway) on the SSO sign-in GET raises
        ``GarminConnectionError`` before sleeping or POSTing credentials.
        """

        # Arrange.
        get_resp = MagicMock()
        get_resp.status_code = 502
        get_resp.ok = False

        mock_session = MagicMock()
        mock_session.get.return_value = get_resp

        with patch("dags.pipelines.garmin.garmin_client.strategies.time.sleep"):
            # Act & Assert.
            with pytest.raises(GarminConnectionError):
                strategies._portal_web_login(mock_client, mock_session, "u", "p")


class TestPortalLoginMobileCffiHardening:
    """
    Tests for Round 3 hardening of ``portal_login`` (mobile cffi flow):

    GET response checks and JSON decode wrapping.
    """

    def test_get_429_raises_before_sleeping(self, mock_client: MagicMock) -> None:
        """
        A 429 on the mobile sign-in GET raises ``GarminTooManyRequestsError`` before any
        delay or POST happens.
        """

        # Arrange.
        get_resp = MagicMock()
        get_resp.status_code = 429
        get_resp.ok = False

        mock_session = MagicMock()
        mock_session.get.return_value = get_resp

        with patch(
            "dags.pipelines.garmin.garmin_client.strategies.HAS_CFFI", True
        ), patch(
            "dags.pipelines.garmin.garmin_client.strategies.cffi_requests"
        ) as mock_cffi, patch(
            "dags.pipelines.garmin.garmin_client.strategies.time.sleep"
        ) as mock_sleep:
            mock_cffi.Session.return_value = mock_session

            # Act & Assert.
            with pytest.raises(GarminTooManyRequestsError):
                strategies.portal_login(mock_client, "u", "p")

            mock_sleep.assert_not_called()
            mock_session.post.assert_not_called()

    def test_post_non_json_raises_connection_error(
        self, mock_client: MagicMock
    ) -> None:
        """
        If the credential POST returns 200 with a non-JSON body (e.g., a Cloudflare edge
        HTML page), the JSON decode failure is wrapped as :class:`GarminConnectionError`
        rather than escaping as a bare decode error.
        """

        # Arrange.
        get_resp = MagicMock()
        get_resp.status_code = 200
        get_resp.ok = True

        post_resp = MagicMock()
        post_resp.status_code = 200
        post_resp.ok = True
        post_resp.text = "<html>edge cache</html>"
        post_resp.json.side_effect = ValueError("not json")

        mock_session = MagicMock()
        mock_session.get.return_value = get_resp
        mock_session.post.return_value = post_resp

        with patch(
            "dags.pipelines.garmin.garmin_client.strategies.HAS_CFFI", True
        ), patch(
            "dags.pipelines.garmin.garmin_client.strategies.cffi_requests"
        ) as mock_cffi, patch(
            "dags.pipelines.garmin.garmin_client.strategies.time.sleep"
        ):
            mock_cffi.Session.return_value = mock_session

            # Act & Assert.
            with pytest.raises(GarminConnectionError, match="non-JSON"):
                strategies.portal_login(mock_client, "u", "p")


class TestCompleteMfaPortalHardening:
    """
    Tests for Round 3 hardening of ``complete_mfa_portal``: status / JSON checks.
    """

    def test_429_raises_too_many_requests(self, mock_client: MagicMock) -> None:
        """
        A 429 from the verifyCode endpoint raises ``GarminTooManyRequestsError`` instead
        of crashing on JSON decode of an HTML rate-limit page.
        """

        # Arrange.
        verify_resp = MagicMock()
        verify_resp.status_code = 429
        verify_resp.ok = False
        verify_resp.text = "Too Many Requests"

        mock_session = MagicMock()
        mock_session.post.return_value = verify_resp
        mock_client._mfa_cffi_session = mock_session
        mock_client._mfa_cffi_params = {}
        mock_client._mfa_cffi_headers = {}

        # Act & Assert.
        with pytest.raises(GarminTooManyRequestsError):
            strategies.complete_mfa_portal(mock_client, "123456")

    def test_non_ok_raises_authentication_error(self, mock_client: MagicMock) -> None:
        """
        Non-2xx responses (e.g., 500) raise ``GarminAuthenticationError`` with a body
        preview rather than calling ``.json()`` on a non-JSON body.
        """

        # Arrange.
        verify_resp = MagicMock()
        verify_resp.status_code = 500
        verify_resp.ok = False
        verify_resp.text = "Internal Server Error"

        mock_session = MagicMock()
        mock_session.post.return_value = verify_resp
        mock_client._mfa_cffi_session = mock_session
        mock_client._mfa_cffi_params = {}
        mock_client._mfa_cffi_headers = {}

        # Act & Assert.
        with pytest.raises(GarminAuthenticationError, match="HTTP 500"):
            strategies.complete_mfa_portal(mock_client, "123456")

    def test_non_json_body_raises_authentication_error(
        self, mock_client: MagicMock
    ) -> None:
        """
        A 200 with a non-JSON body (e.g., a Cloudflare HTML page) is wrapped as
        ``GarminAuthenticationError`` with the JSON decode error chained.
        """

        # Arrange.
        verify_resp = MagicMock()
        verify_resp.status_code = 200
        verify_resp.ok = True
        verify_resp.text = "<html>edge</html>"
        verify_resp.json.side_effect = ValueError("not json")

        mock_session = MagicMock()
        mock_session.post.return_value = verify_resp
        mock_client._mfa_cffi_session = mock_session
        mock_client._mfa_cffi_params = {}
        mock_client._mfa_cffi_headers = {}

        # Act & Assert.
        with pytest.raises(GarminAuthenticationError, match="invalid JSON"):
            strategies.complete_mfa_portal(mock_client, "123456")


class TestCompleteMfaHardening:
    """
    Tests for Round 3 hardening of ``complete_mfa`` (plain-requests mobile flow).
    """

    def test_429_raises_too_many_requests(self, mock_client: MagicMock) -> None:
        """
        A 429 from the verifyCode endpoint raises ``GarminTooManyRequestsError``.
        """

        # Arrange.
        verify_resp = MagicMock()
        verify_resp.status_code = 429
        verify_resp.ok = False
        verify_resp.text = "Too Many Requests"

        mock_session = MagicMock()
        mock_session.post.return_value = verify_resp
        mock_client._mfa_session = mock_session

        # Act & Assert.
        with pytest.raises(GarminTooManyRequestsError):
            strategies.complete_mfa(mock_client, "123456")

    def test_non_ok_raises_authentication_error(self, mock_client: MagicMock) -> None:
        """
        Non-2xx responses raise ``GarminAuthenticationError`` with the status code.
        """

        # Arrange.
        verify_resp = MagicMock()
        verify_resp.status_code = 502
        verify_resp.ok = False
        verify_resp.text = "Bad Gateway"

        mock_session = MagicMock()
        mock_session.post.return_value = verify_resp
        mock_client._mfa_session = mock_session

        # Act & Assert.
        with pytest.raises(GarminAuthenticationError, match="HTTP 502"):
            strategies.complete_mfa(mock_client, "123456")

    def test_non_json_body_raises_authentication_error(
        self, mock_client: MagicMock
    ) -> None:
        """
        A 200 with a non-JSON body wraps the JSON decode error as
        ``GarminAuthenticationError``.
        """

        # Arrange.
        verify_resp = MagicMock()
        verify_resp.status_code = 200
        verify_resp.ok = True
        verify_resp.text = "<html>edge</html>"
        verify_resp.json.side_effect = ValueError("not json")

        mock_session = MagicMock()
        mock_session.post.return_value = verify_resp
        mock_client._mfa_session = mock_session

        # Act & Assert.
        with pytest.raises(GarminAuthenticationError, match="invalid JSON"):
            strategies.complete_mfa(mock_client, "123456")


class TestCompleteMfaPortalWebAggregation:
    """
    Tests for the aggregate failure classification in ``complete_mfa_portal_web``.

    This function tries two endpoints (portal + mobile fallback) and must raise the
    typed exception that matches the underlying cause across both attempts:
    all-429 → GarminTooManyRequestsError, all-transport → GarminConnectionError,
    any verification response → GarminAuthenticationError.
    """

    def _make_portal_web_client(self) -> MagicMock:
        """
        Build a mock client populated with the ``_mfa_portal_web_*`` attributes
        ``complete_mfa_portal_web`` expects to read.
        """

        client = MagicMock()
        client._sso = "https://sso.garmin.com"
        client._mfa_portal_web_session = MagicMock()
        client._mfa_portal_web_params = {"clientId": "GarminConnect"}
        client._mfa_portal_web_headers = {"User-Agent": "test"}
        client._mfa_method = "email"
        return client

    def test_all_429_raises_too_many_requests(self) -> None:
        """
        When every attempted MFA endpoint returns HTTP 429, the aggregate failure is
        rate limiting and should raise ``GarminTooManyRequestsError`` so callers can
        apply backoff instead of treating the failure as bad credentials.
        """

        # Arrange.
        client = self._make_portal_web_client()
        rate_limited = MagicMock()
        rate_limited.status_code = 429
        client._mfa_portal_web_session.post.return_value = rate_limited

        # Act & Assert.
        with pytest.raises(GarminTooManyRequestsError):
            strategies.complete_mfa_portal_web(client, "123456")
        # Both endpoints were tried before classification.
        assert client._mfa_portal_web_session.post.call_count == 2

    def test_all_transport_errors_raise_connection_error(self) -> None:
        """
        When every attempted MFA endpoint fails with a transport-level exception
        (network down, TLS reset), the aggregate failure is infrastructure and should
        raise ``GarminConnectionError`` rather than ``GarminAuthenticationError``.
        """

        # Arrange.
        client = self._make_portal_web_client()
        client._mfa_portal_web_session.post.side_effect = ConnectionError(
            "network down"
        )

        # Act & Assert.
        with pytest.raises(GarminConnectionError) as excinfo:
            strategies.complete_mfa_portal_web(client, "123456")
        # GarminTooManyRequestsError is a subclass of GarminConnectionError, so
        # pin the exact type to make sure the wrong branch wasn't triggered.
        assert type(excinfo.value) is GarminConnectionError
        assert client._mfa_portal_web_session.post.call_count == 2

    def test_all_non_json_responses_raise_connection_error(self) -> None:
        """
        Non-JSON responses (almost always Cloudflare HTML challenges) count as
        transport-level failures for aggregate classification, so two non-JSON responses
        map to ``GarminConnectionError``, not ``GarminAuthenticationError``.
        """

        # Arrange.
        client = self._make_portal_web_client()
        html_resp = MagicMock()
        html_resp.status_code = 200
        html_resp.text = "<html>Cloudflare challenge</html>"
        html_resp.json.side_effect = ValueError("not json")
        client._mfa_portal_web_session.post.return_value = html_resp

        # Act & Assert.
        with pytest.raises(GarminConnectionError) as excinfo:
            strategies.complete_mfa_portal_web(client, "123456")
        assert type(excinfo.value) is GarminConnectionError
        assert client._mfa_portal_web_session.post.call_count == 2

    def test_mixed_429_and_transport_raises_too_many_requests(self) -> None:
        """
        A mix of 429 and transport errors still means no endpoint returned a real
        verification response, and the 429 branch wins over transport (more specific
        signal that Garmin is throttling).
        """

        # Arrange.
        client = self._make_portal_web_client()
        rate_limited = MagicMock()
        rate_limited.status_code = 429
        # First endpoint: 429. Second endpoint: transport error.
        client._mfa_portal_web_session.post.side_effect = [
            rate_limited,
            ConnectionError("tls reset"),
        ]

        # Act & Assert.
        with pytest.raises(GarminTooManyRequestsError):
            strategies.complete_mfa_portal_web(client, "123456")

    def test_any_verification_response_raises_auth_error(self) -> None:
        """
        If at least one endpoint returns a parseable non-SUCCESSFUL JSON body, the
        aggregate is classified as an auth failure regardless of the other endpoint's
        failure mode.

        A real verification response is the definitive signal.
        """

        # Arrange.
        client = self._make_portal_web_client()
        rate_limited = MagicMock()
        rate_limited.status_code = 429
        verify_failed = MagicMock()
        verify_failed.status_code = 200
        verify_failed.ok = True
        verify_failed.json.return_value = {
            "responseStatus": {"type": "INVALID_MFA_CODE"}
        }
        # Endpoint 1: 429. Endpoint 2: real verification failure.
        client._mfa_portal_web_session.post.side_effect = [rate_limited, verify_failed]

        # Act & Assert.
        with pytest.raises(GarminAuthenticationError):
            strategies.complete_mfa_portal_web(client, "123456")

    def test_non_2xx_with_json_body_counts_as_transport_error(self) -> None:
        """
        A non-2xx response with a JSON error body (e.g., HTTP 500 with ``{"error":
        ...}``) means Garmin never reached the MFA verification step, so it must be
        counted as an infrastructure failure.

        Parsing the JSON and falling through to the verification-failure branch would
        mis-credit this as an auth failure, which in turn would swallow retryable
        backend errors behind a GarminAuthenticationError the caller cannot retry.
        """

        # Arrange.
        client = self._make_portal_web_client()
        server_error = MagicMock()
        server_error.status_code = 500
        server_error.ok = False
        server_error.text = '{"error": "internal server error"}'
        # ``r.json()`` would succeed on this body, so the guard must be the
        # ``r.ok`` check rather than a try/except around .json().
        server_error.json.return_value = {"error": "internal server error"}
        client._mfa_portal_web_session.post.return_value = server_error

        # Act & Assert.
        with pytest.raises(GarminConnectionError) as excinfo:
            strategies.complete_mfa_portal_web(client, "123456")
        # Must be the base class, not the 429 subclass: no endpoint returned 429.
        assert type(excinfo.value) is GarminConnectionError
        assert client._mfa_portal_web_session.post.call_count == 2
