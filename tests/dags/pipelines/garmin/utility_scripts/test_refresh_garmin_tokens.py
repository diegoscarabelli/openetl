"""
Unit tests for dags.pipelines.garmin.utility_scripts.refresh_garmin_tokens module.

This test suite covers:
    - Garmin Connect token refresh functionality and error handling.
    - MFA authentication handling.
    - Input validation and credential management.
"""

import os
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from dags.pipelines.garmin.utility_scripts.refresh_garmin_tokens import (
    _handle_mfa_authentication,
    _validate_input,
    get_credentials,
    get_mfa_code,
    refresh_tokens,
)


class TestGarminTokenRefresh:
    """
    Test class for Garmin Connect token refresh functions.
    """

    @pytest.fixture
    def mock_garmin_instance(self) -> MagicMock:
        """
        Create a mock Garmin instance for testing.

        :return: Mock Garmin instance.
        """

        return MagicMock()

    @pytest.fixture
    def mock_garmin_class_with_instance(self, mock_garmin_instance):
        """
        Create a patched Garmin class that returns a mock instance.

        :param mock_garmin_instance: Mock Garmin instance fixture.
        :return: Tuple of mock class and mock instance.
        """

        with patch(
            "dags.pipelines.garmin.utility_scripts.refresh_garmin_tokens.Garmin"
        ) as mock_class:
            mock_class.return_value = mock_garmin_instance
            yield mock_class, mock_garmin_instance

    def test_validate_input_success(self) -> None:
        """
        Test successful input validation.
        """

        # Arrange & Act.
        result = _validate_input("test@example.com", "Email")

        # Assert.
        assert result == "test@example.com"

    def test_validate_input_empty_value(self) -> None:
        """
        Test input validation with empty value.
        """

        # Act & Assert.
        with pytest.raises(ValueError, match="❌ Email is required."):
            _validate_input("", "Email")

    @patch.dict(
        os.environ,
        {"GARMIN_EMAIL": "env@example.com", "GARMIN_PASSWORD": "env_pass"},
    )
    @patch("dags.pipelines.garmin.utility_scripts.refresh_garmin_tokens.logger")
    def test_get_credentials_from_env(self, mock_logger) -> None:
        """
        Test getting credentials from environment variables.

        :param mock_logger: Mock logger instance.
        """

        # Act.
        email, password = get_credentials()

        # Assert.
        assert email == "env@example.com"
        assert password == "env_pass"
        mock_logger.info.assert_called()

    @patch.dict(os.environ, {}, clear=True)
    @patch("builtins.input", side_effect=["user@example.com", "user_password"])
    @patch("dags.pipelines.garmin.utility_scripts.refresh_garmin_tokens.logger")
    def test_get_credentials_from_input(self, mock_logger, _mock_input) -> None:
        """
        Test getting credentials from user input.

        :param mock_logger: Mock logger instance.
        :param _mock_input: Mock input function (unused but needed for patching).
        """

        # Act.
        email, password = get_credentials()

        # Assert.
        assert email == "user@example.com"
        assert password == "user_password"
        mock_logger.info.assert_called()

    @patch("builtins.input", return_value="123456")
    @patch("dags.pipelines.garmin.utility_scripts.refresh_garmin_tokens.logger")
    def test_get_mfa_code_success(self, mock_logger, _mock_input) -> None:
        """
        Test successful MFA code input.

        :param mock_logger: Mock logger instance.
        :param _mock_input: Mock input function (unused but needed for patching).
        """

        # Act.
        mfa_code = get_mfa_code()

        # Assert.
        assert mfa_code == "123456"
        mock_logger.info.assert_called()

    @patch("builtins.input", return_value="abc123")
    @patch("dags.pipelines.garmin.utility_scripts.refresh_garmin_tokens.logger")
    def test_get_mfa_code_invalid_format(self, mock_logger, _mock_input) -> None:
        """
        Test MFA code input with invalid format.

        :param mock_logger: Mock logger instance.
        :param _mock_input: Mock input function (unused but needed for patching).
        """

        # Act.
        mfa_code = get_mfa_code()

        # Assert.
        assert mfa_code == "abc123"  # Function still returns it but logs error.
        mock_logger.error.assert_called_with("⚠️  Error: MFA code should be 6 digits.")

    def test_handle_mfa_authentication_success(
        self, mock_garmin_class_with_instance
    ) -> None:
        """
        Test successful MFA authentication.

        :param mock_garmin_class_with_instance: Mock Garmin class fixture.
        """

        # Arrange.
        _mock_garmin_class, mock_garmin_instance = mock_garmin_class_with_instance
        result2 = "mfa_token"

        with patch(
            "dags.pipelines.garmin.utility_scripts.refresh_garmin_tokens.get_mfa_code",
            return_value="123456",
        ), patch("dags.pipelines.garmin.utility_scripts.refresh_garmin_tokens.logger"):
            # Act.
            _handle_mfa_authentication(mock_garmin_instance, result2)

            # Assert.
            mock_garmin_instance.resume_login.assert_called_once_with(result2, "123456")

    def test_handle_mfa_authentication_failure_retry_success(
        self, mock_garmin_class_with_instance
    ) -> None:
        """
        Test MFA authentication failure followed by successful retry.

        :param mock_garmin_class_with_instance: Mock Garmin class fixture.
        """

        # Arrange.
        _mock_garmin_class, mock_garmin_instance = mock_garmin_class_with_instance
        mock_garmin_instance.resume_login.side_effect = [
            Exception("Invalid MFA"),
            None,
        ]
        result2 = "mfa_token"

        with patch(
            "dags.pipelines.garmin.utility_scripts.refresh_garmin_tokens.get_mfa_code",
            side_effect=["000000", "123456"],
        ), patch("dags.pipelines.garmin.utility_scripts.refresh_garmin_tokens.logger"):
            # Act.
            _handle_mfa_authentication(mock_garmin_instance, result2)

            # Assert
            assert mock_garmin_instance.resume_login.call_count == 2
            mock_garmin_instance.resume_login.assert_has_calls(
                [call(result2, "000000"), call(result2, "123456")]
            )

    def test_handle_mfa_authentication_failure_both_attempts(
        self, mock_garmin_class_with_instance
    ) -> None:
        """
        Test MFA authentication failure on both attempts.

        :param mock_garmin_class_with_instance: Mock Garmin class fixture.
        """

        # Arrange
        _mock_garmin_class, mock_garmin_instance = mock_garmin_class_with_instance
        mock_garmin_instance.resume_login.side_effect = Exception("Invalid MFA")
        result2 = "mfa_token"

        with patch(
            "dags.pipelines.garmin.utility_scripts.refresh_garmin_tokens.get_mfa_code",
            return_value="000000",
        ), patch("dags.pipelines.garmin.utility_scripts.refresh_garmin_tokens.logger"):
            # Act & Assert.
            with pytest.raises(Exception, match="Invalid MFA"):
                _handle_mfa_authentication(mock_garmin_instance, result2)

    def test_refresh_tokens_success_no_mfa(
        self, mock_garmin_class_with_instance, tmp_path
    ) -> None:
        """
        Test successful token refresh without MFA.

        :param mock_garmin_class_with_instance: Mock Garmin class fixture.
        :param tmp_path: Pytest temporary path fixture.
        """

        # Arrange
        mock_garmin_class, mock_garmin_instance = mock_garmin_class_with_instance
        mock_garmin_instance.login.return_value = None  # No MFA required.
        mock_client = MagicMock()
        mock_garmin_instance.client = mock_client

        with patch(
            "dags.pipelines.garmin.utility_scripts.refresh_garmin_tokens.logger"
        ):
            # Act.
            refresh_tokens("test@example.com", "password123", str(tmp_path))

            # Assert
            mock_garmin_class.assert_called_once_with(
                email="test@example.com",
                password="password123",
                is_cn=False,
                return_on_mfa=True,
            )
            mock_garmin_instance.login.assert_called_once()
            mock_client.dump.assert_called_once()

    def test_refresh_tokens_success_with_mfa(
        self, mock_garmin_class_with_instance, tmp_path
    ) -> None:
        """
        Test successful token refresh with MFA.

        :param mock_garmin_class_with_instance: Mock Garmin class fixture.
        :param tmp_path: Pytest temporary path fixture.
        """

        # Arrange
        mock_garmin_class, mock_garmin_instance = mock_garmin_class_with_instance
        mock_garmin_instance.login.return_value = ("needs_mfa", "mfa_token")
        mock_client = MagicMock()
        mock_garmin_instance.client = mock_client

        with patch(
            "dags.pipelines.garmin.utility_scripts.refresh_garmin_tokens."
            "_handle_mfa_authentication"
        ) as mock_handle_mfa, patch(
            "dags.pipelines.garmin.utility_scripts.refresh_garmin_tokens.logger"
        ):
            # Act.
            refresh_tokens("test@example.com", "password123", str(tmp_path))

            # Assert
            mock_garmin_class.assert_called_once_with(
                email="test@example.com",
                password="password123",
                is_cn=False,
                return_on_mfa=True,
            )
            mock_garmin_instance.login.assert_called_once()
            mock_handle_mfa.assert_called_once_with(mock_garmin_instance, "mfa_token")
            mock_client.dump.assert_called_once()

    def test_refresh_tokens_authentication_failure(
        self, mock_garmin_class_with_instance, tmp_path
    ) -> None:
        """
        Test token refresh with authentication failure.

        :param mock_garmin_class_with_instance: Mock Garmin class fixture.
        :param tmp_path: Pytest temporary path fixture.
        """

        # Arrange
        _mock_garmin_class, mock_garmin_instance = mock_garmin_class_with_instance
        mock_garmin_instance.login.side_effect = Exception("401 Unauthorized")

        with patch(
            "dags.pipelines.garmin.utility_scripts.refresh_garmin_tokens.logger"
        ), patch(
            "dags.pipelines.garmin.utility_scripts.refresh_garmin_tokens."
            "_print_troubleshooting"
        ):
            # Act & Assert.
            with pytest.raises(Exception, match="401 Unauthorized"):
                refresh_tokens("invalid@example.com", "wrong_password", str(tmp_path))

            # Should not call client.dump if login fails.
            mock_garmin_instance.client.dump.assert_not_called()


class TestRefreshTokensMultiAccount:
    """
    Test class for multi-account token storage behavior in refresh_tokens.

    Verifies that tokens are saved to user-specific subdirectories and that the user ID
    is correctly detected from the Garmin profile API.
    """

    @pytest.fixture
    def mock_garmin_instance(self) -> MagicMock:
        """
        Create a mock Garmin instance for testing.

        :return: Mock Garmin instance.
        """

        return MagicMock()

    @pytest.fixture
    def mock_garmin_class_with_instance(self, mock_garmin_instance):
        """
        Create a patched Garmin class that returns a mock instance.

        :param mock_garmin_instance: Mock Garmin instance fixture.
        :return: Tuple of mock class and mock instance.
        """

        with patch(
            "dags.pipelines.garmin.utility_scripts.refresh_garmin_tokens.Garmin"
        ) as mock_class:
            mock_class.return_value = mock_garmin_instance
            yield mock_class, mock_garmin_instance

    def test_refresh_tokens_saves_to_user_subdir(
        self, mock_garmin_class_with_instance, tmp_path
    ) -> None:
        """
        Test that refresh_tokens saves tokens to a subdirectory named by user ID.

        After login, the function calls get_user_profile() to obtain the user ID, then
        saves tokens to base_token_dir/<user_id>/.

        :param mock_garmin_class_with_instance: Mock Garmin class fixture.
        :param tmp_path: Pytest temporary path fixture.
        """

        # Arrange.
        _mock_garmin_class, mock_garmin_instance = mock_garmin_class_with_instance
        mock_garmin_instance.login.return_value = None  # No MFA required.
        mock_garmin_instance.get_user_profile.return_value = {"id": "12345678"}
        mock_client = MagicMock()
        mock_garmin_instance.client = mock_client

        with patch(
            "dags.pipelines.garmin.utility_scripts.refresh_garmin_tokens.logger"
        ):
            # Act.
            refresh_tokens("test@example.com", "password123", str(tmp_path))

            # Assert.
            dump_call_args = mock_client.dump.call_args[0][0]
            assert Path(dump_call_args).name == "12345678"
            mock_garmin_instance.get_user_profile.assert_called_once()

    def test_refresh_tokens_missing_user_id(
        self, mock_garmin_class_with_instance, tmp_path
    ) -> None:
        """
        Test that refresh_tokens raises RuntimeError when user ID is missing from
        profile.

        If get_user_profile() returns a dict without an "id" key, the function should
        raise RuntimeError since the user-specific token directory cannot be determined.

        :param mock_garmin_class_with_instance: Mock Garmin class fixture.
        :param tmp_path: Pytest temporary path fixture.
        """

        # Arrange.
        _mock_garmin_class, mock_garmin_instance = mock_garmin_class_with_instance
        mock_garmin_instance.login.return_value = None  # No MFA required.
        mock_garmin_instance.get_user_profile.return_value = {}  # No "id" key.

        with patch(
            "dags.pipelines.garmin.utility_scripts.refresh_garmin_tokens.logger"
        ), patch(
            "dags.pipelines.garmin.utility_scripts.refresh_garmin_tokens."
            "_print_troubleshooting"
        ):
            # Act & Assert.
            with pytest.raises(RuntimeError, match="Could not determine user ID"):
                refresh_tokens("test@example.com", "password123", str(tmp_path))

            # Should not call client.dump if user ID is missing.
            mock_garmin_instance.client.dump.assert_not_called()

    def test_refresh_tokens_with_mfa(
        self, mock_garmin_class_with_instance, tmp_path
    ) -> None:
        """
        Test that refresh_tokens handles MFA flow and saves tokens to user subdirectory.

        When login returns ("needs_mfa", token), the MFA handler is invoked, and after
        successful authentication, tokens are saved to base_token_dir/<user_id>/.

        :param mock_garmin_class_with_instance: Mock Garmin class fixture.
        :param tmp_path: Pytest temporary path fixture.
        """

        # Arrange.
        _mock_garmin_class, mock_garmin_instance = mock_garmin_class_with_instance
        mock_garmin_instance.login.return_value = ("needs_mfa", "mfa_token")
        mock_garmin_instance.get_user_profile.return_value = {"id": "12345678"}
        mock_client = MagicMock()
        mock_garmin_instance.client = mock_client

        with patch(
            "dags.pipelines.garmin.utility_scripts.refresh_garmin_tokens."
            "_handle_mfa_authentication"
        ) as mock_handle_mfa, patch(
            "dags.pipelines.garmin.utility_scripts.refresh_garmin_tokens.logger"
        ):
            # Act.
            refresh_tokens("test@example.com", "password123", str(tmp_path))

            # Assert: MFA handler was called.
            mock_handle_mfa.assert_called_once_with(mock_garmin_instance, "mfa_token")

            # Assert: tokens saved to user-specific subdirectory.
            dump_call_args = mock_client.dump.call_args[0][0]
            assert Path(dump_call_args).name == "12345678"
