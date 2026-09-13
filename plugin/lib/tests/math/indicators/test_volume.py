"""Tests for plugin/lib/math/indicators/volume.py, hand-computed
fixtures.
"""

from datetime import UTC, datetime, timedelta

import pytest

from lib.math.exceptions import InsufficientDataError
from lib.math.indicators.volume import (
    compute_above_average_volume,
    compute_accumulation_distribution,
    compute_obv,
    compute_vwap,
)
from lib.mechanics.models import Bar

_START = datetime(2026, 1, 1, tzinfo=UTC)


def _bar(day: int, high: float, low: float, close: float, volume: int) -> Bar:
    return Bar(
        symbol="TEST", interval="1d", ts=_START + timedelta(days=day),
        open=close, high=high, low=low, close=close, volume=volume, provider="test",
    )


def test_compute_above_average_volume_ratio() -> None:
    bars = [_bar(i, 100.0, 100.0, 100.0, 100) for i in range(19)]
    bars.append(_bar(19, 100.0, 100.0, 100.0, 300))
    ratio = compute_above_average_volume(bars, window=20)
    assert ratio == pytest.approx(300 / 110.0)


def test_compute_above_average_volume_raises_when_insufficient_bars() -> None:
    bars = [_bar(i, 100.0, 100.0, 100.0, 100) for i in range(5)]
    with pytest.raises(InsufficientDataError):
        compute_above_average_volume(bars, window=20)


def test_compute_obv_accumulates_by_direction() -> None:
    closes = [10.0, 12.0, 11.0, 15.0]
    volumes = [100, 200, 150, 300]
    bars = [_bar(i, c, c, c, v) for i, (c, v) in enumerate(zip(closes, volumes, strict=True))]
    # ta's OBV convention seeds from the first bar's own volume, not zero:
    # OBV[0]=100, +200 (12>10) -> 300, -150 (11<12) -> 150, +300 (15>11) -> 450
    assert compute_obv(bars) == pytest.approx(450.0)


def test_compute_obv_raises_when_insufficient_bars() -> None:
    with pytest.raises(InsufficientDataError):
        compute_obv([_bar(0, 100.0, 100.0, 100.0, 100)])


def test_compute_vwap_weighted_by_volume() -> None:
    bars = [_bar(0, 10.0, 8.0, 9.0, 100), _bar(1, 12.0, 10.0, 11.0, 200)]
    # tp: (10+8+9)/3=9, (12+10+11)/3=11; weighted=(9*100+11*200)/300
    assert compute_vwap(bars) == pytest.approx((9 * 100 + 11 * 200) / 300)


def test_compute_vwap_raises_on_zero_total_volume() -> None:
    bars = [_bar(0, 10.0, 8.0, 9.0, 0)]
    with pytest.raises(ValueError):
        compute_vwap(bars)


def test_compute_accumulation_distribution_sums_clv_times_volume() -> None:
    bars = [_bar(0, 10.0, 8.0, 9.0, 100), _bar(1, 10.0, 8.0, 10.0, 500)]
    # bar0 clv=((9-8)-(10-9))/(10-8)=0 -> contributes 0
    # bar1 clv=((10-8)-(10-10))/(10-8)=1 -> contributes 500
    assert compute_accumulation_distribution(bars) == pytest.approx(500.0)


def test_compute_accumulation_distribution_skips_zero_range_bars() -> None:
    bars = [_bar(0, 10.0, 10.0, 10.0, 100)]
    assert compute_accumulation_distribution(bars) == pytest.approx(0.0)
