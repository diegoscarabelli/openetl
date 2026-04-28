"""
Unit tests for dags.pipelines.garmin.garmin_client.exceptions module.

Verifies the inheritance graph that lets callers catch a single
``GarminConnectionError`` to handle both rate-limit and generic transport errors.
"""

from dags.pipelines.garmin.garmin_client.exceptions import (
    GarminAuthenticationError,
    GarminConnectionError,
    GarminTooManyRequestsError,
)


def test_too_many_requests_is_a_connection_error() -> None:
    """
    ``GarminTooManyRequestsError`` subclasses ``GarminConnectionError`` so callers can
    catch the parent to handle all transport-level failures.
    """
    err = GarminTooManyRequestsError("rate limited")
    assert isinstance(err, GarminConnectionError)
    assert isinstance(err, Exception)


def test_authentication_error_is_independent() -> None:
    """
    Authentication errors are deliberately not connection errors so credential failures
    don't get masked by a generic try/except.
    """
    err = GarminAuthenticationError("bad password")
    assert not isinstance(err, GarminConnectionError)
    assert isinstance(err, Exception)
