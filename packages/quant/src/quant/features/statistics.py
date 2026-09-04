import math
import statistics
from datetime import datetime

import pandas as pd

from quant.core.constants import (
    ANNUALIZATION_FACTOR_ANNUALLY,
    ANNUALIZATION_FACTOR_DAILY,
    ANNUALIZATION_FACTOR_MONTHLY,
    ANNUALIZATION_FACTOR_QUARTERLY,
    ANNUALIZATION_FACTOR_SEMI_MONTHLY,
    ANNUALIZATION_FACTOR_WEEKLY,
    CALENDAR_DAYS_PER_YEAR,
    RISK_FREE_RATE_DAY_COUNT_DIVISOR,
)
from quant.core.exceptions import InsufficientDataError


def _period_returns(closes: list[float]) -> list[float]:
    return [
        (closes[i] - closes[i - 1]) / closes[i - 1]
        for i in range(1, len(closes))
        if closes[i - 1] != 0
    ]


def _check_same_length(closes: list[float], timestamps: list[datetime], fn_name: str) -> None:
    if len(closes) != len(timestamps):
        raise ValueError(
            f"{fn_name} needs one timestamp per close, got {len(closes)} closes "
            f"and {len(timestamps)} timestamps"
        )


def _excess_return_levels(
    closes: list[float], timestamps: list[datetime], risk_free_rate: float
) -> list[float]:
    """Excess-return level series: `closes` with the risk-free rate's drag
    removed day by day, Actual/360 day count. With `risk_free_rate=0.0`
    this telescopes back to `closes` exactly (no drag to remove).
    """
    levels = [closes[0]]
    for j in range(1, len(closes)):
        fraction = (timestamps[j] - timestamps[j - 1]).days / RISK_FREE_RATE_DAY_COUNT_DIVISOR
        levels.append(
            levels[-1] + closes[j] - closes[j - 1] * (1 + risk_free_rate * fraction)
        )
    return levels


def _annualization_factor(timestamps: list[datetime]) -> int:
    """Infers an annualization factor from the average number of calendar
    days between consecutive observations (daily/weekly/monthly/etc.).
    """
    distances = [
        (timestamps[i] - timestamps[i - 1]).days for i in range(1, len(timestamps))
    ]
    if any(d == 0 for d in distances):
        raise InsufficientDataError("multiple data points on the same date")
    average_distance = sum(distances) / len(distances)

    if average_distance < 2.1:
        return ANNUALIZATION_FACTOR_DAILY
    if 6 <= average_distance < 8:
        return ANNUALIZATION_FACTOR_WEEKLY
    if 14 <= average_distance < 17:
        return ANNUALIZATION_FACTOR_SEMI_MONTHLY
    if 25 <= average_distance < 35:
        return ANNUALIZATION_FACTOR_MONTHLY
    if 85 <= average_distance < 97:
        return ANNUALIZATION_FACTOR_QUARTERLY
    if 360 <= average_distance < 386:
        return ANNUALIZATION_FACTOR_ANNUALLY
    raise InsufficientDataError(
        f"cannot infer an annualization factor, average distance between "
        f"observations: {average_distance} days"
    )


def total_return(closes: list[float]) -> float:
    """Simple total return over `closes`, start to end, not annualized."""
    if len(closes) < 2:
        raise InsufficientDataError(f"total_return needs at least 2 closes, got {len(closes)}")
    if closes[0] == 0:
        raise InsufficientDataError("total_return got a zero starting close")
    return (closes[-1] - closes[0]) / closes[0]


def annualized_return(
    closes: list[float], timestamps: list[datetime], risk_free_rate: float = 0.0
) -> float:
    """Compound annualized return over `closes`, Actual/365.25 day count
    on real elapsed calendar time. `risk_free_rate`, if given, is removed
    from the return day by day (Actual/360) before annualizing, same
    excess-return treatment `sharpe_ratio` uses.
    """
    _check_same_length(closes, timestamps, "annualized_return")
    if len(closes) < 2:
        raise InsufficientDataError(f"annualized_return needs at least 2 closes, got {len(closes)}")
    elapsed_days = (timestamps[-1] - timestamps[0]).days
    if elapsed_days <= 0:
        raise InsufficientDataError("timestamps must span a positive number of calendar days")

    levels = _excess_return_levels(closes, timestamps, risk_free_rate)
    return float((levels[-1] / levels[0]) ** (CALENDAR_DAYS_PER_YEAR / elapsed_days) - 1.0)


def max_drawdown(closes: list[float]) -> float:
    """Largest peak-to-trough decline in `closes`, as a negative fraction
    (for example -0.25 for a 25% drawdown). Zero if the series never
    falls below a prior peak.
    """
    if len(closes) < 2:
        raise InsufficientDataError(f"max_drawdown needs at least 2 closes, got {len(closes)}")
    peak = closes[0]
    worst = 0.0
    for price in closes[1:]:
        peak = max(peak, price)
        if peak == 0:
            continue
        drawdown = (price - peak) / peak
        worst = min(worst, drawdown)
    return worst


def sharpe_ratio(
    closes: list[float], timestamps: list[datetime], risk_free_rate: float = 0.0
) -> float:
    """Sharpe ratio of `closes` over the full span: annualized excess
    return over annualized volatility (sample stdev, N-1), both derived
    from real elapsed calendar time, times 100.

    `risk_free_rate` is removed from the return day by day (Actual/360)
    before either leg is computed, matching gs-quant's excess-returns
    treatment. This is the float-rate path only, deliberately: gs-quant's
    own currency-keyed risk-free curve is fetched from GS Marquee's data
    service, proprietary infra this repo does not depend on (see
    docs/features/gs-quant-integration-ideas.md).
    """
    _check_same_length(closes, timestamps, "sharpe_ratio")
    if len(closes) < 3:
        raise InsufficientDataError(f"sharpe_ratio needs at least 3 closes, got {len(closes)}")

    levels = _excess_return_levels(closes, timestamps, risk_free_rate)
    elapsed_days = (timestamps[-1] - timestamps[0]).days
    if elapsed_days <= 0:
        raise InsufficientDataError("timestamps must span a positive number of calendar days")
    ann_return = (levels[-1] / levels[0]) ** (CALENDAR_DAYS_PER_YEAR / elapsed_days) - 1.0

    period_returns = _period_returns(levels)
    if len(period_returns) < 2:
        raise InsufficientDataError(
            f"sharpe_ratio needs at least 2 valid returns, got {len(period_returns)}"
        )
    sample_stdev = statistics.stdev(period_returns)
    if sample_stdev == 0:
        return 0.0
    factor = _annualization_factor(timestamps)
    ann_vol_pct = sample_stdev * math.sqrt(factor) * 100.0

    return float(ann_return / ann_vol_pct * 100.0)


def exponential_std(closes: list[float], beta: float = 0.75) -> float:
    """Exponentially weighted standard deviation of period-over-period
    returns, `beta` controlling how much weight the (more distant) past
    carries, matching pandas' `ewm(alpha=1-beta, adjust=False).std()`
    (an unbiased weighted-variance estimator, not a naive weighted
    average). `beta` must be in [0, 1), 0 puts all weight on the most
    recent return, close to 1 nearly flattens the weighting.
    """
    if not (0.0 <= beta < 1.0):
        raise ValueError("beta must be in [0, 1)")
    returns = _period_returns(closes)
    if len(returns) < 2:
        raise InsufficientDataError(
            f"exponential_std needs at least 2 valid returns, got {len(returns)}"
        )
    result = pd.Series(returns).ewm(alpha=1.0 - beta, adjust=False).std().iloc[-1]
    return float(result)
