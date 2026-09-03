import math
from datetime import UTC, datetime

import pytest
from quant.core.interfaces import Forecast
from quant.core.portfolio_sizer import PortfolioSizer
from quant.core.sizer import PositionSizer


def _forecast(symbol: str, scaled_value: float) -> Forecast:
    return Forecast(
        symbol=symbol,
        interval="1d",
        ts=datetime(2026, 1, 1, tzinfo=UTC),
        name="rsi",
        scaled_value=scaled_value,
    )


def test_uncorrelated_symbols_scaled_down_by_sqrt_n() -> None:
    forecasts = {"A": _forecast("A", 20.0), "B": _forecast("B", 20.0)}
    volatilities = {"A": 0.02, "B": 0.02}
    prices = {"A": 1000.0, "B": 500.0}
    identity_correlation = {("A", "A"): 1.0, ("B", "B"): 1.0, ("A", "B"): 0.0, ("B", "A"): 0.0}
    account_equity = 100_000.0

    sizer = PortfolioSizer(target_risk_pct=0.02)
    sizes = sizer.size_all(forecasts, volatilities, prices, identity_correlation, account_equity)

    raw_sizer = PositionSizer(target_risk_pct=0.02)
    raw_a = raw_sizer.size(forecasts["A"], volatilities["A"], account_equity, prices["A"])
    raw_b = raw_sizer.size(forecasts["B"], volatilities["B"], account_equity, prices["B"])

    # Two uncorrelated symbols each at full individual risk budget combine to
    # sqrt(2) times that budget at the portfolio level, so each gets scaled
    # down by 1/sqrt(2) to bring total portfolio risk back to target.
    assert sizes["A"].size == pytest.approx(raw_a.size / math.sqrt(2))
    assert sizes["B"].size == pytest.approx(raw_b.size / math.sqrt(2))


def test_correlated_symbols_sized_down_more_than_uncorrelated() -> None:
    forecasts = {"A": _forecast("A", 20.0), "B": _forecast("B", 20.0)}
    volatilities = {"A": 0.02, "B": 0.02}
    prices = {"A": 1000.0, "B": 500.0}
    account_equity = 100_000.0

    sizer = PortfolioSizer(target_risk_pct=0.02)
    identity_correlation = {("A", "A"): 1.0, ("B", "B"): 1.0, ("A", "B"): 0.0, ("B", "A"): 0.0}
    correlated = {("A", "A"): 1.0, ("B", "B"): 1.0, ("A", "B"): 0.9, ("B", "A"): 0.9}

    uncorrelated_sizes = sizer.size_all(
        forecasts, volatilities, prices, identity_correlation, account_equity
    )
    correlated_sizes = sizer.size_all(forecasts, volatilities, prices, correlated, account_equity)

    assert abs(correlated_sizes["A"].size) < abs(uncorrelated_sizes["A"].size)
    assert abs(correlated_sizes["B"].size) < abs(uncorrelated_sizes["B"].size)


def test_single_symbol_matches_independent_sizing_unscaled() -> None:
    forecasts = {"A": _forecast("A", 10.0)}
    volatilities = {"A": 0.02}
    prices = {"A": 1000.0}
    correlation = {("A", "A"): 1.0}
    account_equity = 100_000.0

    sizer = PortfolioSizer(target_risk_pct=0.02)
    sizes = sizer.size_all(forecasts, volatilities, prices, correlation, account_equity)

    raw_sizer = PositionSizer(target_risk_pct=0.02)
    raw_a = raw_sizer.size(forecasts["A"], volatilities["A"], account_equity, prices["A"])

    # A single symbol never exceeds the portfolio risk cap on its own
    # (target_risk_pct is the same cap for one asset as for the whole book),
    # so no scale-down applies.
    assert sizes["A"].size == pytest.approx(raw_a.size)
