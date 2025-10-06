"""
Garmin Connect Token Refresh Utility.

This utility script is designed to refresh Garmin Connect authentication tokens
used by the Airflow pipeline, with support for Multi-Factor Authentication.

PURPOSE:
What the script does:
1. Authenticates with Garmin Connect using your credentials.
2. Automatically detects if MFA is required.
3. Handles MFA by prompting for your 6-digit code (if MFA is enabled).
4. Works seamlessly for accounts without MFA enabled.
5. Saves tokens to ~/.garminconnect (same location used by pipeline).
6. Validates the authentication was successful.

WHEN TO USE:
Run this script when:
- Setting up the pipeline for the first time.
- Tokens have expired (approximately every 1 year).
- MFA authentication is required.
- The Airflow DAG fails due to authentication errors.

USAGE:
    python refresh_garmin_tokens.py

The script will prompt for:
    - Garmin Connect email.
    - Garmin Connect password.
    - MFA code (if MFA is enabled on your account).

TROUBLESHOOTING:
Common Issues:
1. MFA Code Invalid/Expired.
   - MFA codes expire quickly (usually 30-60 seconds).
   - Generate a fresh code and try again immediately.

2. Wrong Credentials.
   - Verify email and password are correct.
   - Check for typos or case sensitivity.

3. Account Configuration Issues.
   - The script works with or without MFA enabled on your account.
   - If you have MFA enabled but aren't being prompted, check your account.
   - If authentication fails repeatedly, try the Garmin Connect website first.

4. Network Issues.
   - Ensure you have internet connectivity.
   - Check if Garmin Connect services are operational.

TOKEN STORAGE:
Tokens are saved to ~/.garminconnect/ which is the same location used by:
- The Airflow pipeline (extract.py).
- The python-garminconnect library.
- The underlying Garth authentication library.

SECURITY NOTES:
- Tokens are stored locally in your home directory.
- Tokens are valid for approximately 1 year.
- The script does not store your password or MFA codes.
- Only OAuth tokens are persisted for future authentication.
"""

import os
import traceback

from pathlib import Path
from typing import Tuple

from garminconnect import Garmin

from dags.lib.logging_utils import LOGGER

# Use the global logger instance.
logger = LOGGER


def _validate_input(value: str, field_name: str) -> str:
    """
    Validate user input is not empty.

    :param value: Input value to validate.
    :param field_name: Name of the field for error messages.
    :return: Validated input value.
    """

    if not value:
        raise ValueError(f"❌ {field_name} is required.")
    return value


def _print_troubleshooting() -> None:
    """
    Print common troubleshooting steps.
    """

    logger.info(
        "\n🔍 Troubleshooting:"
        "\n   - Verify your email and password are correct."
        "\n   - Check for typos or case sensitivity."
        "\n   - Ensure you have internet connectivity."
        "\n   - If MFA is enabled, make sure the MFA code is current."
        "\n   - Try running the script again."
        "\n   - Check if Garmin Connect services are operational."
    )


def get_credentials() -> Tuple[str, str]:
    """
    Get Garmin Connect credentials from user input.

    :return: Tuple of (email, password).
    """

    logger.info(f"🔐 Garmin Connect Token Refresh Utility.\n{'=' * 50}")

    # Try environment variables first.
    email = os.getenv("GARMIN_EMAIL")
    password = os.getenv("GARMIN_PASSWORD")

    if email and password:
        logger.info(
            f"📧 Using credentials from environment variables.\n   Email: {email}."
        )
        return email, password

    # Prompt for credentials.
    logger.info("📧 Enter your Garmin Connect credentials.")
    email = _validate_input(input("   Email: ").strip(), "Email")
    password = _validate_input(input("   Password: ").strip(), "Password")

    return email, password


def get_mfa_code() -> str:
    """
    Prompt user for MFA code.

    :return: MFA code string.
    """

    logger.info(
        "\n🔢 Multi-Factor Authentication Required."
        "\n   Check your email or phone for the MFA code."
    )

    mfa_code = _validate_input(input("   Enter MFA code: ").strip(), "MFA code")

    if not mfa_code.isdigit() or len(mfa_code) != 6:
        logger.error("⚠️  Error: MFA code should be 6 digits.")

    return mfa_code


def _handle_mfa_authentication(garmin, result2) -> None:
    """
    Handle MFA authentication with one retry attempt.

    :param garmin: Garmin client instance.
    :param result2: MFA continuation token from login result.
    """

    logger.info("✅ Initial authentication successful.")

    for attempt in range(2):  # Allow 2 attempts (0 and 1)
        try:
            mfa_code = get_mfa_code()
            logger.info("🔢 Completing MFA authentication...")
            garmin.resume_login(result2, mfa_code)
            logger.info("✅ MFA authentication successful.")
            return  # Success, exit function

        except Exception:
            if attempt == 0:  # First attempt failed
                logger.error(
                    f"❌ MFA authentication failed:\n{traceback.format_exc()}."
                )
                logger.info("🔄 Please try again with a fresh MFA code.")
                continue
            # Second attempt failed.
            logger.error(
                f"❌ MFA authentication failed after 2 attempts:\n"
                f"{traceback.format_exc()}"
            )
            raise  # Re-raise the exception


def refresh_tokens(email: str, password: str, token_dir: str = "~/.garminconnect"):
    """
    Refresh Garmin Connect tokens with MFA support.

    :param email: Garmin Connect email.
    :param password: Garmin Connect password.
    :param token_dir: Directory to store tokens.
    """

    token_path = Path(token_dir).expanduser()

    logger.info(
        f"\n🔄 Authenticating with Garmin Connect...\n   Token storage: {token_path}."
    )

    try:
        # Initialize Garmin client with MFA support.
        # is_cn=False connects to international servers (garmin.com).
        # vs Chinese (garmin.cn).
        garmin = Garmin(email=email, password=password, is_cn=False, return_on_mfa=True)

        # Attempt login.
        login_result = garmin.login()

        # Handle different return value formats.
        if isinstance(login_result, tuple) and len(login_result) == 2:
            result1, result2 = login_result

            # Handle MFA if required.
            if result1 == "needs_mfa":
                _handle_mfa_authentication(garmin, result2)
            else:
                logger.info("✅ Authentication successful (no MFA required).")
        else:
            # Handle case where login() returns single value or None (no MFA).
            logger.info("✅ Authentication successful (no MFA required).")

        logger.info("💾 Saving authentication tokens...")

        # Ensure token directory exists with proper permissions.
        token_path.mkdir(parents=True, exist_ok=True)
        token_path.chmod(0o755)

        garmin.garth.dump(str(token_path))

        logger.info(
            f"✅ Tokens successfully saved to {token_path}.\n"
            "🎯 Token refresh complete!\n\n"
            "🎉 Success! Your Garmin Connect tokens have been refreshed.\n"
            "   Your Airflow pipeline will now use these fresh tokens.\n\n"
            "ℹ️  These tokens are valid for approximately 1 year."
        )

    except Exception:
        logger.error(f"❌ Authentication failed:\n{traceback.format_exc()}.")
        _print_troubleshooting()
        raise


def main() -> None:
    """
    Main function to orchestrate token refresh process.
    """

    # Get credentials.
    email, password = get_credentials()

    # Refresh tokens.
    refresh_tokens(email, password)


if __name__ == "__main__":
    main()
