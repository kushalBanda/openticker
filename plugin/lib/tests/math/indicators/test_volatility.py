"""Tests for plugin/lib/math/indicators/volatility.py. Bollinger and ATR
verify the seam into ta; realized volatility is hand-rolled and gets a
hand-computed fixture, since ta has no equivalent function.
"""

from datetime import UTC, datetime, timedelta

import pytest

from lib.math.exceptions import InsufficientDataError
from lib.math.indicators.volatility import (
    compute_atr,
    compute_bollinger_bands,
    compute_realized_volatility,
)
from lib.mechanics.models import Bar

_START = datetime(2026, 1, 1, tzinfo=UTC)


def _bar(day: int, open_: float, high: float, low: float, close: float) -> Bar:
    return Bar(
        symbol="TEST", interval="1d", ts=_START + timedelta(days=day),
        open=open_, high=high, low=low, close=close, volume=1000, provider="test",
    )


def _flat_bars(count: int, close: float) -> list[Bar]:
    return [_bar(i, close, close, close, close) for i in range(count)]


def test_compute_bollinger_bands_classic_stdev_example() -> None:
    # Textbook population-stdev example: [2,4,4,4,5,5,7,9], mean=5, std=2.
    closes = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    bars = [_bar(i, c, c, c, c) for i, c in enumerate(closes)]
    reading = compute_bollinger_bands(bars, window=8, window_dev=2)
    assert reading.middle == pytest.approx(5.0)
    assert reading.upper == pytest.approx(9.0)
    assert reading.lower == pytest.approx(1.0)


def test_compute_bollinger_bands_raises_when_insufficient_bars() -> None:
    with pytest.raises(InsufficientDataError):
        compute_bollinger_bands(_flat_bars(5, 100.0), window=20)


def test_compute_atr_constant_range() -> None:
    bars = [_bar(i, 100.0, 105.0, 95.0, 100.0) for i in range(7)]
    reading = compute_atr(bars, window=5)
    assert reading.latest == pytest.approx(10.0)


def test_compute_atr_raises_when_insufficient_bars() -> None:
    with pytest.raises(InsufficientDataError):
        compute_atr(_flat_bars(3, 100.0), window=14)


def test_compute_realized_volatility_zero_variance_is_zero() -> None:
    bars = _flat_bars(21, 100.0)
    assert compute_realized_volatility(bars, window=20) == pytest.approx(0.0)


def test_compute_realized_volatility_raises_when_insufficient_bars() -> None:
    with pytest.raises(InsufficientDataError):
        compute_realized_volatility(_flat_bars(5, 100.0), window=20)
