"""Tests for plugin/lib/math/indicators/cross_sectional.py,
hand-computed fixtures. Every function here takes two aligned bar
series, index-for-index - these tests build both series with the same
length and the same timestamps for that reason.
"""

from datetime import UTC, datetime, timedelta

import pytest

from lib.math.exceptions import InsufficientDataError
from lib.math.indicators.cross_sectional import (
    compute_beta,
    compute_correlation,
    compute_pairs_spread,
    compute_relative_strength,
)
from lib.mechanics.models import Bar

_START = datetime(2026, 1, 1, tzinfo=UTC)


def _closes_to_bars(closes: list[float]) -> list[Bar]:
    return [
        Bar(
            symbol="TEST", interval="1d", ts=_START + timedelta(days=i),
            open=c, high=c, low=c, close=c, volume=1000, provider="test",
        )
        for i, c in enumerate(closes)
    ]


def test_compute_relative_strength_ratio_of_ratios() -> None:
    symbol_bars = _closes_to_bars([100.0] * 20 + [120.0])
    benchmark_bars = _closes_to_bars([100.0] * 20 + [110.0])
    rs = compute_relative_strength(symbol_bars, benchmark_bars, period=20)
    assert rs == pytest.approx((120.0 / 100.0) / (110.0 / 100.0) * 100)


def test_compute_relative_strength_raises_when_insufficient_bars() -> None:
    with pytest.raises(InsufficientDataError):
        compute_relative_strength(_closes_to_bars([100.0] * 5), _closes_to_bars([100.0] * 5), period=20)


def test_compute_correlation_identical_return_patterns_is_one() -> None:
    closes_a = [100.0, 110.0, 104.5, 125.4]  # returns: 0.1, -0.05, 0.2
    closes_b = [50.0, 55.0, 52.25, 62.7]      # same return pattern, different scale
    corr = compute_correlation(_closes_to_bars(closes_a), _closes_to_bars(closes_b), period=3)
    assert corr == pytest.approx(1.0)


def test_compute_correlation_raises_when_insufficient_bars() -> None:
    with pytest.raises(InsufficientDataError):
        compute_correlation(_closes_to_bars([100.0] * 3), _closes_to_bars([100.0] * 3), period=20)


def test_compute_beta_matches_hand_computed_ratio() -> None:
    # benchmark returns: 0.1, -0.05, 0.2; symbol returns exactly double
    bench_closes = [100.0, 110.0, 104.5, 125.4]
    symbol_closes = [100.0, 120.0, 108.0, 151.2]
    beta = compute_beta(_closes_to_bars(symbol_closes), _closes_to_bars(bench_closes), period=3)
    assert beta == pytest.approx(2.0, rel=1e-6)


def test_compute_beta_raises_when_insufficient_bars() -> None:
    with pytest.raises(InsufficientDataError):
        compute_beta(_closes_to_bars([100.0] * 3), _closes_to_bars([100.0] * 3), period=20)


def test_compute_pairs_spread_identical_series_is_flat() -> None:
    closes = [100.0] * 10
    reading = compute_pairs_spread(_closes_to_bars(closes), _closes_to_bars(closes), lookback=10)
    assert reading.spread == pytest.approx(0.0)
    assert reading.zscore == pytest.approx(0.0)


def test_compute_pairs_spread_raises_when_insufficient_bars() -> None:
    with pytest.raises(InsufficientDataError):
        compute_pairs_spread(_closes_to_bars([100.0] * 3), _closes_to_bars([100.0] * 3), lookback=10)
