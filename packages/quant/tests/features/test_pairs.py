from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from quant.core.exceptions import InsufficientDataError
from quant.features.pairs import (
    SpreadBaseline,
    select_pairs,
    spread_baseline,
    spread_value,
    zscore,
)


def _series(values: list[float]) -> pd.Series:
    start = datetime(2026, 1, 1, tzinfo=UTC)
    index = pd.DatetimeIndex([start + timedelta(days=i) for i in range(len(values))])
    return pd.Series(values, index=index, dtype=float)


def test_select_pairs_ranks_tightest_comovement_first() -> None:
    closes = {
        "A": _series([100.0, 101.0, 102.0, 103.0, 104.0]),
        "B": _series([100.0, 101.0, 102.0, 103.0, 104.0]),
        "C": _series([100.0, 110.0, 90.0, 130.0, 60.0]),
    }
    result = select_pairs(closes, top_n=3)
    assert {result[0].symbol_a, result[0].symbol_b} == {"A", "B"}
    assert result[0].ssd == pytest.approx(0.0)


def test_select_pairs_returns_at_most_top_n() -> None:
    closes = {
        "A": _series([100.0, 101.0, 102.0]),
        "B": _series([100.0, 105.0, 103.0]),
        "C": _series([100.0, 95.0, 110.0]),
        "D": _series([100.0, 120.0, 80.0]),
    }
    result = select_pairs(closes, top_n=2)
    assert len(result) == 2


def test_select_pairs_raises_with_fewer_than_two_symbols() -> None:
    with pytest.raises(InsufficientDataError):
        select_pairs({"A": _series([100.0, 101.0])}, top_n=1)


def test_spread_baseline_matches_manual_mean_and_std() -> None:
    closes_a = _series([100.0, 110.0, 120.0])
    closes_b = _series([100.0, 105.0, 110.0])
    baseline = spread_baseline(closes_a, closes_b, anchor_a=100.0, anchor_b=100.0)
    assert baseline.mean == pytest.approx(0.05)
    assert baseline.std == pytest.approx(0.05)


def test_spread_baseline_raises_on_zero_std() -> None:
    closes_a = _series([100.0, 110.0, 120.0])
    closes_b = _series([100.0, 110.0, 120.0])
    with pytest.raises(InsufficientDataError):
        spread_baseline(closes_a, closes_b, anchor_a=100.0, anchor_b=100.0)


def test_spread_value_uses_symbol_specific_anchors() -> None:
    same_anchor = spread_value(price_a=110.0, price_b=105.0, anchor_a=100.0, anchor_b=100.0)
    different_anchor = spread_value(price_a=110.0, price_b=105.0, anchor_a=100.0, anchor_b=50.0)
    assert same_anchor == pytest.approx(0.05)
    assert different_anchor == pytest.approx(-1.0)


def test_zscore_matches_manual_formula() -> None:
    baseline = SpreadBaseline(mean=0.05, std=0.05)
    assert zscore(0.15, baseline) == pytest.approx(2.0)
