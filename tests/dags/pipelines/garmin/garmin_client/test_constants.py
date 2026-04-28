"""
Unit tests for dags.pipelines.garmin.garmin_client.constants module.

Covers the helper functions and shape of the SSO/DI/API constants used by the vendored
Garmin Connect client.
"""

import base64

from dags.pipelines.garmin.garmin_client.constants import (
    DI_CLIENT_IDS,
    DI_GRANT_TYPE,
    DI_TOKEN_URL,
    LOGIN_DELAY_MAX_S,
    LOGIN_DELAY_MIN_S,
    NATIVE_API_USER_AGENT,
    NATIVE_X_GARMIN_USER_AGENT,
    _build_basic_auth,
    _native_headers,
    _random_browser_headers,
)


class TestRandomBrowserHeaders:
    """
    Tests for ``_random_browser_headers``.
    """

    def test_returns_dict_with_user_agent(self) -> None:
        """
        The helper always returns a dict containing a User-Agent header.

        ``ua_generator`` (when installed) emits lowercase header names while the static
        fallback uses the canonical capitalized form, so this check accepts either case.
        """
        # Act.
        headers = _random_browser_headers()

        # Assert.
        assert isinstance(headers, dict)
        ua_keys = [k for k in headers if k.lower() == "user-agent"]
        assert len(ua_keys) == 1
        assert headers[ua_keys[0]]


class TestBuildBasicAuth:
    """
    Tests for ``_build_basic_auth``.
    """

    def test_returns_basic_prefix_and_base64(self) -> None:
        """
        ``_build_basic_auth`` returns ``Basic <base64(client_id:)>`` per the DI OAuth2
        endpoint's expectations.
        """
        # Arrange.
        client_id = "GARMIN_TEST_CLIENT"

        # Act.
        header_value = _build_basic_auth(client_id)

        # Assert.
        assert header_value.startswith("Basic ")
        encoded = header_value[len("Basic ") :]
        decoded = base64.b64decode(encoded).decode()
        assert decoded == f"{client_id}:"


class TestNativeHeaders:
    """
    Tests for ``_native_headers``.
    """

    def test_default_headers_contain_required_fields(self) -> None:
        """
        Without extras the helper returns the static native Android headers including
        the GCM User-Agent and X-Garmin-User-Agent strings.
        """
        # Act.
        headers = _native_headers()

        # Assert.
        assert headers["User-Agent"] == NATIVE_API_USER_AGENT
        assert headers["X-Garmin-User-Agent"] == NATIVE_X_GARMIN_USER_AGENT
        assert headers["X-Garmin-Client-Platform"] == "Android"
        assert "Accept-Language" in headers

    def test_extra_headers_merge_on_top(self) -> None:
        """
        Extras override defaults when keys collide.
        """
        # Arrange.
        extra = {"Authorization": "Bearer abc", "User-Agent": "override"}

        # Act.
        headers = _native_headers(extra)

        # Assert.
        assert headers["Authorization"] == "Bearer abc"
        assert headers["User-Agent"] == "override"
        # Defaults still present.
        assert "X-Garmin-User-Agent" in headers


class TestModuleConstants:
    """
    Smoke tests for the module-level constants.
    """

    def test_login_delay_bounds_are_sane(self) -> None:
        """
        The Cloudflare-evading delay should sit in the 30-60s range and have a non-empty
        span (otherwise ``random.uniform`` would always return the same value).
        """
        assert 30.0 <= LOGIN_DELAY_MIN_S < LOGIN_DELAY_MAX_S
        assert LOGIN_DELAY_MAX_S <= 60.0

    def test_di_client_ids_is_non_empty_tuple(self) -> None:
        """
        The DI exchange iterates this tuple in order, so it must be non-empty and
        contain only strings.
        """
        assert isinstance(DI_CLIENT_IDS, tuple)
        assert len(DI_CLIENT_IDS) >= 1
        assert all(isinstance(cid, str) and cid for cid in DI_CLIENT_IDS)

    def test_di_token_endpoints_are_https_urls(self) -> None:
        """
        The DI token endpoint and grant type are HTTPS URLs at garmin.com.
        """
        assert DI_TOKEN_URL.startswith("https://")
        assert "garmin.com" in DI_TOKEN_URL
        assert DI_GRANT_TYPE.startswith("https://")
