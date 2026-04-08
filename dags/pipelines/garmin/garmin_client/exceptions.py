"""
Exceptions raised by the vendored Garmin Connect client.

These exceptions mirror the upstream ``python-garminconnect`` library's
``GarminConnect*Error`` types but use shorter names to make the vendored origin
explicit.
"""


class GarminAuthenticationError(Exception):
    """
    Authentication failed.

    Raised for bad credentials, expired tokens, missing MFA prompts, MFA failures, or DI
    token exchange failures.
    """


class GarminConnectionError(Exception):
    """
    Network or HTTP error talking to Garmin Connect.

    Raised when the Garmin API returns a non-success status code that does not indicate
    an authentication or rate-limit problem, or when a transport-level error prevents
    the request from completing.
    """


class GarminTooManyRequestsError(GarminConnectionError):
    """
    Garmin or Cloudflare returned HTTP 429.

    Subclass of ``GarminConnectionError`` so callers that want to handle all
    connection problems uniformly can catch the parent class while callers that
    care about rate limiting specifically can catch this subclass.
    """
