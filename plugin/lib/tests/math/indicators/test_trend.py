"""Tests for plugin/lib/math/indicators/trend.py. Verifies the seam
(bars in, ta called correctly, TrailingReading shape out) - not ta's
own formula correctness, which is that library's tested responsibility.
"""

from datetime import UTC, datetime, timedelta

import pytest

from lib.math.exceptions import InsufficientDataError
from lib.math.indicators.trend import (
    compute_adx,
    compute_ema,
    compute_macd,
    compute_parabolic_sar,
    compute_sma,
    compute_wma,
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


def test_compute_sma_averages_last_n_closes() -> None:
    closes = [1.0, 2.0, 3.0, 4.0, 5.0]
    bars = [_bar(i, c, c, c, c) for i, c in enumerate(closes)]
    reading = compute_sma(bars, window=5)
    assert reading.latest == pytest.approx(3.0)


def test_compute_sma_raises_when_insufficient_bars() -> None:
    with pytest.raises(InsufficientDataError):
        compute_sma(_flat_bars(3, 100.0), window=5)


def test_compute_ema_flat_series_equals_the_flat_value() -> None:
    reading = compute_ema(_flat_bars(15, 100.0), window=10)
    assert reading.latest == pytest.approx(100.0)
    assert reading.trailing == pytest.approx([100.0] * 5)


def test_compute_ema_raises_when_insufficient_bars() -> None:
    with pytest.raises(InsufficientDataError):
        compute_ema(_flat_bars(9, 100.0), window=10)


def test_compute_wma_raises_when_insufficient_bars() -> None:
    with pytest.raises(InsufficientDataError):
        compute_wma(_flat_bars(2, 100.0), window=9)


def test_compute_macd_flat_series_is_zero() -> None:
    reading = compute_macd(_flat_bars(40, 100.0), window_slow=26, window_fast=12, window_sign=9)
    assert reading.macd.latest == pytest.approx(0.0)
    assert reading.signal.latest == pytest.approx(0.0)
    assert reading.histogram.latest == pytest.approx(0.0)


def test_compute_macd_raises_when_insufficient_bars() -> None:
    with pytest.raises(InsufficientDataError):
        compute_macd(_flat_bars(20, 100.0), window_slow=26)


def test_compute_adx_flat_series_is_zero() -> None:
    reading = compute_adx(_flat_bars(30, 100.0), window=14)
    assert reading.adx.latest == pytest.approx(0.0)


def test_compute_adx_uptrend_favors_plus_di() -> None:
    bars = [_bar(i, 95.0 + i, 100.0 + i, 95.0 + i, 98.0 + i) for i in range(30)]
    reading = compute_adx(bars, window=14)
    assert reading.plus_di.latest > reading.minus_di.latest


def test_compute_adx_raises_when_insufficient_bars() -> None:
    with pytest.raises(InsufficientDataError):
        compute_adx(_flat_bars(20, 100.0), window=14)


def test_compute_parabolic_sar_raises_when_insufficient_bars() -> None:
    with pytest.raises(InsufficientDataError):
        compute_parabolic_sar(_flat_bars(2, 100.0))


def test_compute_parabolic_sar_returns_trailing_reading() -> None:
    bars = [
        _bar(0, 9.0, 10.0, 8.0, 9.0),
        _bar(1, 9.0, 12.0, 9.0, 11.0),
        _bar(2, 10.0, 13.0, 10.0, 12.0),
        _bar(3, 12.0, 15.0, 11.0, 14.0),
        _bar(4, 12.0, 16.0, 12.0, 15.0),
    ]
    reading = compute_parabolic_sar(bars, trailing_count=2)
    assert isinstance(reading.latest, float)
    assert len(reading.trailing) == 2
