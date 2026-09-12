import pandas as pd
import pytest

from lib.math.statistics import max_drawdown, sharpe_ratio, total_return


def test_max_drawdown_is_zero_for_monotonic_uptrend() -> None:
    series = pd.Series([100.0, 110.0, 120.0])
    assert max_drawdown(series) == 0.0


def test_max_drawdown_detects_peak_to_trough() -> None:
    series = pd.Series([100.0, 120.0, 90.0])
    assert max_drawdown(series) == pytest.approx(-0.25)


def test_total_return_simple_case() -> None:
    series = pd.Series([100.0, 150.0])
    assert total_return(series) == pytest.approx(0.5)


def test_sharpe_ratio_zero_when_no_volatility() -> None:
    index = pd.date_range("2026-01-01", periods=5, freq="D")
    series = pd.Series([100.0, 100.0, 100.0, 100.0, 100.0], index=index)
    assert sharpe_ratio(series) == 0.0
