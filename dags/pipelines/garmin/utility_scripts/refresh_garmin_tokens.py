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
5. Auto-detects the Garmin user ID after authentication.
6. Saves tokens to ~/.garminconnect/<user_id>/ for multi-account support.
7. Validates the authentication was successful.

MULTI-ACCOUNT SUPPORT:
The pipeline supports multiple Garmin Connect accounts (e.g., family members).
Run this script once per account to set up tokens. Each account's tokens are
stored in a separate subdirectory named by the Garmin user ID:
    ~/.garminconnect/12345678/
    ~/.garminconnect/87654321/

The pipeline automatically discovers all configured accounts by scanning
subdirectories in ~/.garminconnect/ at runtime.

WHEN TO USE:
Run this script when:
- Setting up the pipeline for the first time (once per account).
- Tokens have expired (approximately every 1 year).
- MFA authentication is required.
- The Airflow DAG fails due to authentication errors.
- Adding a new Garmin Connect account to the pipeline.

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
Tokens are saved to ~/.garminconnect/<user_id>/ where <user_id> is the Garmin
Connect numeric user ID, automatically detected after authentication. This
location is used by:
- The Airflow pipeline (extract.py) for multi-account data extraction.
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


def refresh_tokens(email: str, password: str, base_token_dir: str = "~/.garminconnect"):
    """
    Refresh Garmin Connect tokens with MFA support.

    After successful authentication, the Garmin user ID is auto-detected via the
    user profile API. Tokens are saved to a user-specific subdirectory:
    ``<base_token_dir>/<user_id>/``.

    :param email: Garmin Connect email.
    :param password: Garmin Connect password.
    :param base_token_dir: Base directory for token storage. Tokens will be saved
        to a ``<user_id>`` subdirectory within this directory.
    """

    base_path = Path(base_token_dir).expanduser()

    logger.info(
        f"\n🔄 Authenticating with Garmin Connect...\n"
        f"   Base token directory: {base_path}."
    )

    try:
        # Initialize Garmin client with MFA support.
        # is_cn=False connects to international servers (garmin.com).
        # vs Chinese (garmin.cn).
        garmin = Garmin(email=email, password=password, is_cn=False, return_on_mfa=True)

        # Override garth's default User-Agent ("GCM-iOS-5.7.2.1") with a
        # browser string. Garmin's Cloudflare blocks the mobile app identifier
        # for programmatic SSO login, but allows browser User-Agents through.
        garmin.garth.sess.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                )
            }
        )

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

        # Auto-detect user ID from the authenticated profile.
        user_id = garmin.get_user_profile().get("id")
        if not user_id:
            raise RuntimeError(
                "Could not determine user ID from Garmin profile. "
                "The 'id' field was missing from get_user_profile() response."
            )

        logger.info(f"👤 Detected Garmin user ID: {user_id}.")

        # Build user-specific token path: ~/.garminconnect/<user_id>/
        token_path = base_path / str(user_id)

        logger.info(f"💾 Saving authentication tokens to {token_path}...")

        # Ensure directories exist with user-only permissions (tokens are secrets).
        base_path.mkdir(parents=True, exist_ok=True)
        base_path.chmod(0o700)
        token_path.mkdir(exist_ok=True)
        token_path.chmod(0o700)

        garmin.garth.dump(str(token_path))

        # Lock down token files to owner-only (garth.dump uses default umask).
        for token_file in token_path.iterdir():
            token_file.chmod(0o600)

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
