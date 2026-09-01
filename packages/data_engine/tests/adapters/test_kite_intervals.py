import data_engine.adapters.kite.intervals
import pytest
from data_engine.core.constants import CANONICAL_INTERVALS, PROVIDER_KITE
from data_engine.core.exceptions import DataUnavailableError
from data_engine.core.intervals import to_provider_interval


@pytest.mark.parametrize(
    ("canonical", "expected"),
    [("1m", "minute"), ("3m", "3minute"), ("5m", "5minute"), ("1d", "day")],
)
def test_to_provider_interval_kite(canonical: str, expected: str) -> None:
    assert to_provider_interval(PROVIDER_KITE, canonical) == expected


def test_kite_map_covers_every_canonical_interval() -> None:
    for interval in CANONICAL_INTERVALS:
        assert to_provider_interval(PROVIDER_KITE, interval)


def test_kite_unknown_interval_raises() -> None:
    with pytest.raises(DataUnavailableError):
        to_provider_interval(PROVIDER_KITE, "2h")
