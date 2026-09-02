import pytest
from ingest.adapters.groww.intervals import GROWW_INTERVAL_MAP
from ingest.core.constants import CANONICAL_INTERVALS, PROVIDER_GROWW
from ingest.core.exceptions import DataUnavailableError
from ingest.core.intervals import register_interval_map, to_provider_interval

register_interval_map(PROVIDER_GROWW, GROWW_INTERVAL_MAP)


@pytest.mark.parametrize(
    ("canonical", "expected"),
    [("1m", "1minute"), ("5m", "5minute"), ("1d", "1day")],
)
def test_to_provider_interval_groww(canonical: str, expected: str | int) -> None:
    assert to_provider_interval(PROVIDER_GROWW, canonical) == expected


def test_groww_map_covers_every_canonical_interval() -> None:
    for interval in CANONICAL_INTERVALS:
        assert to_provider_interval(PROVIDER_GROWW, interval)


def test_groww_unknown_interval_raises() -> None:
    with pytest.raises(DataUnavailableError):
        to_provider_interval(PROVIDER_GROWW, "2h")
