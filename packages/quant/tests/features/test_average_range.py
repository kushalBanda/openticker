from datetime import UTC, datetime

import pytest
from ingest.core.models import Bar
from quant.core.exceptions import InsufficientDataError
from quant.features.volatility import average_range


def _bars(ranges: list[tuple[float, float]]) -> list[Bar]:
    return [
        Bar(
            symbol="RELIANCE",
            interval="1d",
            ts=datetime(2026, 1, 1, tzinfo=UTC),
            open=low,
            high=high,
            low=low,
            close=high,
            volume=1000,
            provider="synthetic",
        )
        for low, high in ranges
    ]


def test_average_range_matches_mean_high_low_span() -> None:
    bars = _bars([(10.0, 12.0), (10.0, 14.0), (10.0, 13.0)])
    assert average_range(bars, 3) == pytest.approx(3.0)


def test_average_range_uses_only_last_window_bars() -> None:
    bars = _bars([(10.0, 20.0), (10.0, 11.0), (10.0, 11.0)])
    assert average_range(bars, 2) == pytest.approx(1.0)


def test_average_range_raises_when_insufficient_bars() -> None:
    bars = _bars([(10.0, 12.0)])
    with pytest.raises(InsufficientDataError):
        average_range(bars, 3)
