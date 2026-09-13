"""Tests for plugin/lib/math/position_sizing.py, hand-computed fixtures."""

from datetime import UTC, datetime, timedelta

import pytest

from lib.math.exceptions import InsufficientDataError
from lib.math.position_sizing import (
    suggest_position_size,
    suggest_stop_distance,
    suggest_take_profit,
)
from lib.mechanics.models import Bar

_START = datetime(2026, 1, 1, tzinfo=UTC)


def _bar(day: int, low: float, close: float) -> Bar:
    return Bar(
        symbol="TEST", interval="1d", ts=_START + timedelta(days=day),
        open=close, high=close + 1, low=low, close=close, volume=1000, provider="test",
    )


def test_suggest_stop_distance_uses_lowest_low_in_lookback() -> None:
    lows = [10.0, 8.0, 12.0, 9.0, 11.0, 7.0, 13.0, 10.0, 9.0, 8.0]
    bars = [_bar(i, low, close=20.0) for i, low in enumerate(lows)]
    distance = suggest_stop_distance(bars, lookback=10)
    assert distance == pytest.approx(20.0 - 7.0)


def test_suggest_stop_distance_raises_when_insufficient_bars() -> None:
    bars = [_bar(i, 10.0, close=20.0) for i in range(5)]
    with pytest.raises(InsufficientDataError):
        suggest_stop_distance(bars, lookback=10)


def test_suggest_stop_distance_raises_when_entry_at_or_below_structural_low() -> None:
    bars = [_bar(i, 10.0, close=10.0) for i in range(10)]
    with pytest.raises(ValueError):
        suggest_stop_distance(bars, lookback=10)


def test_suggest_position_size_caps_by_risk_amount() -> None:
    quantity = suggest_position_size(capital=100_000.0, risk_per_trade_pct=1.0, stop_distance=13.0, price=20.0)
    assert quantity == 76  # floor(1000 / 13) = 76


def test_suggest_position_size_returns_zero_when_capital_too_small() -> None:
    quantity = suggest_position_size(capital=50.0, risk_per_trade_pct=1.0, stop_distance=13.0, price=20.0)
    assert quantity == 0  # floor(0.5 / 13) = 0


def test_suggest_position_size_raises_on_non_positive_stop_distance() -> None:
    with pytest.raises(ValueError):
        suggest_position_size(capital=100_000.0, risk_per_trade_pct=1.0, stop_distance=0.0, price=20.0)


def test_suggest_take_profit_applies_reward_risk_ratio() -> None:
    target = suggest_take_profit(entry_price=100.0, stop_distance=10.0, reward_risk_ratio=2.0)
    assert target == pytest.approx(120.0)


def test_suggest_take_profit_default_ratio_is_two() -> None:
    target = suggest_take_profit(entry_price=100.0, stop_distance=10.0)
    assert target == pytest.approx(120.0)
