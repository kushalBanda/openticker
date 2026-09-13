"""Tests for plugin/lib/math/indicators/structure.py, hand-computed
fixtures.
"""

from datetime import UTC, datetime, timedelta

import pytest

from lib.math.exceptions import InsufficientDataError
from lib.math.indicators.structure import (
    compute_52_week_range_position,
    compute_breakout,
    compute_candlestick_pattern,
    compute_gap,
    compute_pivot_points,
    compute_support_resistance,
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


def test_compute_breakout_detects_upward_break() -> None:
    bars = [_bar(i, 100.0, 105.0, 95.0, 100.0) for i in range(20)]
    bars.append(_bar(20, 100.0, 112.0, 100.0, 110.0))
    reading = compute_breakout(bars)
    assert reading.direction == "up"
    assert reading.level == pytest.approx(105.0)
    assert reading.breakout_pct == pytest.approx((110.0 - 105.0) / 105.0 * 100)


def test_compute_breakout_detects_downward_break() -> None:
    bars = [_bar(i, 100.0, 105.0, 95.0, 100.0) for i in range(20)]
    bars.append(_bar(20, 90.0, 90.0, 80.0, 85.0))
    reading = compute_breakout(bars)
    assert reading.direction == "down"
    assert reading.level == pytest.approx(95.0)
    assert reading.breakout_pct == pytest.approx((95.0 - 85.0) / 95.0 * 100)


def test_compute_breakout_no_break_inside_range() -> None:
    bars = [_bar(i, 100.0, 105.0, 95.0, 100.0) for i in range(20)]
    bars.append(_bar(20, 100.0, 102.0, 98.0, 101.0))
    reading = compute_breakout(bars)
    assert reading.direction == "none"
    assert reading.breakout_pct == 0.0


def test_compute_breakout_raises_when_insufficient_bars() -> None:
    with pytest.raises(InsufficientDataError):
        compute_breakout(_flat_bars(10, 100.0))


def test_compute_support_resistance_uses_window_extremes() -> None:
    bars = [_bar(i, 100.0, 105.0 + i, 95.0 - i, 100.0) for i in range(20)]
    reading = compute_support_resistance(bars, lookback=20)
    assert reading.resistance == pytest.approx(105.0 + 19)
    assert reading.support == pytest.approx(95.0 - 19)


def test_compute_support_resistance_raises_when_insufficient_bars() -> None:
    with pytest.raises(InsufficientDataError):
        compute_support_resistance(_flat_bars(5, 100.0), lookback=20)


def test_compute_candlestick_pattern_bullish_engulfing() -> None:
    prev = _bar(0, 100.0, 101.0, 95.0, 96.0)
    last = _bar(1, 95.0, 106.0, 94.0, 101.0)
    assert compute_candlestick_pattern([prev, last]).pattern == "bullish_engulfing"


def test_compute_candlestick_pattern_bearish_engulfing() -> None:
    prev = _bar(0, 96.0, 101.0, 95.0, 100.0)
    last = _bar(1, 101.0, 102.0, 89.0, 90.0)
    assert compute_candlestick_pattern([prev, last]).pattern == "bearish_engulfing"


def test_compute_candlestick_pattern_doji() -> None:
    prev = _bar(0, 100.0, 101.0, 99.0, 100.0)
    last = _bar(1, 100.0, 105.0, 95.0, 100.2)
    assert compute_candlestick_pattern([prev, last]).pattern == "doji"


def test_compute_candlestick_pattern_hammer() -> None:
    prev = _bar(0, 100.0, 101.0, 99.0, 100.0)
    last = _bar(1, 100.0, 102.5, 90.0, 102.0)
    assert compute_candlestick_pattern([prev, last]).pattern == "hammer"


def test_compute_candlestick_pattern_shooting_star() -> None:
    prev = _bar(0, 100.0, 101.0, 99.0, 100.0)
    last = _bar(1, 100.0, 110.0, 97.5, 98.0)
    assert compute_candlestick_pattern([prev, last]).pattern == "shooting_star"


def test_compute_candlestick_pattern_custom_threshold_changes_result() -> None:
    prev = _bar(0, 100.0, 101.0, 99.0, 100.0)
    last = _bar(1, 100.0, 105.0, 95.0, 100.2)  # body/range=0.02, doji at default 0.1
    assert compute_candlestick_pattern([prev, last], doji_body_to_range_max=0.01).pattern == "none"


def test_compute_candlestick_pattern_raises_when_insufficient_bars() -> None:
    with pytest.raises(InsufficientDataError):
        compute_candlestick_pattern(_flat_bars(1, 100.0))


def test_compute_gap_up() -> None:
    bars = [_bar(0, 100.0, 101.0, 99.0, 100.0), _bar(1, 105.0, 106.0, 104.0, 105.5)]
    reading = compute_gap(bars)
    assert reading.gap_pct == pytest.approx(5.0)
    assert reading.direction == "up"


def test_compute_gap_raises_when_insufficient_bars() -> None:
    with pytest.raises(InsufficientDataError):
        compute_gap([_bar(0, 100.0, 101.0, 99.0, 100.0)])


def test_compute_52_week_range_position_midpoint() -> None:
    bars = [_bar(i, 100.0, 110.0, 90.0, 100.0) for i in range(10)]
    assert compute_52_week_range_position(bars, lookback_bars=10) == pytest.approx(50.0)


def test_compute_52_week_range_position_raises_when_insufficient_bars() -> None:
    with pytest.raises(InsufficientDataError):
        compute_52_week_range_position(_flat_bars(5, 100.0), lookback_bars=252)


def test_compute_pivot_points_matches_classic_formula() -> None:
    prev = _bar(0, 100.0, 110.0, 90.0, 100.0)
    today = _bar(1, 100.0, 101.0, 99.0, 100.0)
    reading = compute_pivot_points([prev, today])
    assert reading.pivot == pytest.approx(100.0)
    assert reading.r1 == pytest.approx(110.0)
    assert reading.s1 == pytest.approx(90.0)
    assert reading.r2 == pytest.approx(120.0)
    assert reading.s2 == pytest.approx(80.0)
    assert reading.r3 == pytest.approx(130.0)
    assert reading.s3 == pytest.approx(70.0)


def test_compute_pivot_points_raises_when_insufficient_bars() -> None:
    with pytest.raises(InsufficientDataError):
        compute_pivot_points([_bar(0, 100.0, 101.0, 99.0, 100.0)])
