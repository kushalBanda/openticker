import pytest
from ingest.core.exceptions import DataUnavailableError
from ingest.core.intervals import register_interval_map, to_provider_interval


def test_to_provider_interval_uses_registered_map() -> None:
    register_interval_map("fake-provider", {"1m": "M1"})
    assert to_provider_interval("fake-provider", "1m") == "M1"


def test_to_provider_interval_unknown_provider_raises() -> None:
    with pytest.raises(DataUnavailableError):
        to_provider_interval("no-such-provider", "1m")


def test_to_provider_interval_unknown_interval_raises() -> None:
    register_interval_map("another-fake-provider", {"1m": "M1"})
    with pytest.raises(DataUnavailableError):
        to_provider_interval("another-fake-provider", "2h")
