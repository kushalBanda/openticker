"""Tests for plugin/lib/math/indicators/momentum.py. Verifies the seam
(bars in, ta called correctly, TrailingReading shape out), not ta's own
formula correctness.
"""

from datetime import UTC, datetime, timedelta

import pytest

from lib.math.exceptions import InsufficientDataError
from lib.math.indicators.momentum import (
    compute_cci,
    compute_roc,
    compute_rsi,
    compute_stochastic,
    compute_stochastic_rsi,
    compute_williams_r,
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


def test_compute_rsi_zero_loss_is_100() -> None:
    closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
    bars = [_bar(i, c, c, c, c) for i, c in enumerate(closes)]
    reading = compute_rsi(bars, window=3)
    assert reading.latest == pytest.approx(100.0)


def test_compute_rsi_raises_when_insufficient_bars() -> None:
    with pytest.raises(InsufficientDataError):
        compute_rsi(_flat_bars(3, 100.0), window=14)


def test_compute_stochastic_flat_series() -> None:
    bars = [_bar(i, 100.0, 105.0, 95.0, 100.0) for i in range(10)]
    reading = compute_stochastic(bars, window=3, smooth_window=2)
    assert reading.k.latest == pytest.approx(50.0)
    assert reading.d.latest == pytest.approx(50.0)


def test_compute_stochastic_raises_when_insufficient_bars() -> None:
    bars = [_bar(i, 100.0, 105.0, 95.0, 100.0) for i in range(3)]
    with pytest.raises(InsufficientDataError):
        compute_stochastic(bars, window=14)


def test_compute_stochastic_rsi_raises_when_insufficient_bars() -> None:
    with pytest.raises(InsufficientDataError):
        compute_stochastic_rsi(_flat_bars(10, 100.0), window=14)


def test_compute_stochastic_rsi_returns_k_and_d() -> None:
    # A strictly monotonic series pins RSI at 100 past the warmup window,
    # which makes StochRSI's rolling min/max range zero (0/0 = NaN
    # forever) - a real degenerate case in ta's own formula, not a bug in
    # the wrapper. Use a fluctuating fixture so RSI actually varies.
    closes = [100.0]
    for i in range(69):
        closes.append(closes[-1] + (3.0 if i % 3 else -2.0))
    bars = [_bar(i, c, c + 1.0, c - 1.0, c) for i, c in enumerate(closes)]
    reading = compute_stochastic_rsi(bars, window=14)
    assert isinstance(reading.stochrsi.latest, float)
    assert isinstance(reading.k.latest, float)
    assert isinstance(reading.d.latest, float)


def test_compute_williams_r_mid_range() -> None:
    bars = [_bar(i, 100.0, 110.0, 90.0, 100.0) for i in range(14)]
    reading = compute_williams_r(bars, lbp=14)
    assert reading.latest == pytest.approx(-50.0)


def test_compute_williams_r_raises_when_insufficient_bars() -> None:
    with pytest.raises(InsufficientDataError):
        compute_williams_r(_flat_bars(5, 100.0), lbp=14)


def test_compute_roc_percent_change_over_period() -> None:
    closes = [100.0] * 12 + [110.0]
    bars = [_bar(i, c, c, c, c) for i, c in enumerate(closes)]
    reading = compute_roc(bars, window=12)
    assert reading.latest == pytest.approx(10.0)


def test_compute_roc_raises_when_insufficient_bars() -> None:
    with pytest.raises(InsufficientDataError):
        compute_roc(_flat_bars(5, 100.0), window=12)


def test_compute_cci_zero_deviation_raises_insufficient_data() -> None:
    # A fully flat series has zero mean deviation, so ta's own CCI formula
    # divides 0/0 (NaN) at every point - a real degenerate case, not a
    # wrapper bug. The wrapper surfaces that as InsufficientDataError
    # rather than silently returning 0.0.
    with pytest.raises(InsufficientDataError):
        compute_cci(_flat_bars(20, 100.0), window=20)


def test_compute_cci_raises_when_insufficient_bars() -> None:
    with pytest.raises(InsufficientDataError):
        compute_cci(_flat_bars(5, 100.0), window=20)
