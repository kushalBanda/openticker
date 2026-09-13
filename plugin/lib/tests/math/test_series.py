"""Tests for the two new converters added to plugin/lib/math/series.py."""

from datetime import UTC, datetime, timedelta

from lib.math.series import bar_highs_to_series, bar_lows_to_series
from lib.mechanics.models import Bar

_START = datetime(2026, 1, 1, tzinfo=UTC)


def _bar(day: int, high: float, low: float) -> Bar:
    return Bar(
        symbol="TEST", interval="1d", ts=_START + timedelta(days=day),
        open=high, high=high, low=low, close=high, volume=1000, provider="test",
    )


def test_bar_highs_to_series_extracts_highs() -> None:
    bars = [_bar(0, 10.0, 5.0), _bar(1, 12.0, 6.0)]
    series = bar_highs_to_series(bars)
    assert list(series) == [10.0, 12.0]


def test_bar_lows_to_series_extracts_lows() -> None:
    bars = [_bar(0, 10.0, 5.0), _bar(1, 12.0, 6.0)]
    series = bar_lows_to_series(bars)
    assert list(series) == [5.0, 6.0]
