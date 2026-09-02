import pytest
from ingest.adapters.kite.intervals import KITE_INTERVAL_MAP
from ingest.core.constants import CANONICAL_INTERVALS, PROVIDER_KITE
from ingest.core.exceptions import DataUnavailableError
from ingest.core.intervals import register_interval_map, to_provider_interval

register_interval_map(PROVIDER_KITE, KITE_INTERVAL_MAP)


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
