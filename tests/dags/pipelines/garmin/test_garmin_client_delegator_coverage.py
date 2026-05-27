"""
Parametric coverage test for ``GarminClient`` delegators.

The extractor calls ``getattr(self.garmin_client, data_type.api_method)``. A delegator
method missing from ``GarminClient`` would raise ``AttributeError`` only at extract
time: the unit tests for the plain ``api.<method>`` functions can't catch it because
they call the module-level function directly. This parametric test walks
``GARMIN_DATA_REGISTRY`` and asserts every registered ``api_method`` is a callable
attribute on ``GarminClient``.

Mirrors the regression guard from garmin-health-data#63 / #65.
"""

import pytest

from dags.pipelines.garmin.constants import GARMIN_DATA_REGISTRY
from dags.pipelines.garmin.garmin_client import GarminClient


@pytest.mark.parametrize(
    "data_type",
    GARMIN_DATA_REGISTRY.all_data_types,
    ids=lambda dt: dt.name,
)
def test_every_registered_api_method_exists_on_client(data_type) -> None:
    """
    Every registered ``api_method`` must be a callable attribute on ``GarminClient``.

    :param data_type: GarminDataType iterated over by pytest parametrize.
    """
    method = getattr(GarminClient, data_type.api_method, None)
    assert method is not None, (
        f"GarminClient is missing delegator for {data_type.name}: "
        f"expected attribute '{data_type.api_method}' was not found."
    )
    assert callable(
        method
    ), f"GarminClient.{data_type.api_method} exists but is not callable."
