"""Return/risk statistics on a price series: total/annualized return,
Sharpe ratio, max drawdown, exponential std.

Ported verbatim from quant.features.statistics - already flat module
level functions, no registry, no class.
"""

import math

import pandas as pd

from lib.math.constants import (
    ANNUALIZATION_FACTOR_ANNUALLY,
    ANNUALIZATION_FACTOR_DAILY,
    ANNUALIZATION_FACTOR_MONTHLY,
    ANNUALIZATION_FACTOR_QUARTERLY,
    ANNUALIZATION_FACTOR_SEMI_MONTHLY,
    ANNUALIZATION_FACTOR_WEEKLY,
    CALENDAR_DAYS_PER_YEAR,
    RISK_FREE_RATE_DAY_COUNT_DIVISOR,
)
from lib.math.exceptions import InsufficientDataError


def _period_returns(x: pd.Series) -> pd.Series:
    prev = x.shift(1)
    returns = (x - prev) / prev
    return returns[prev.notna() & (prev != 0)]


def _excess_return_levels(closes: pd.Series, risk_free_rate: float) -> pd.Series:
    index = closes.index
    levels = [float(closes.iloc[0])]
    for j in range(1, len(closes)):
        fraction = (index[j] - index[j - 1]).days / RISK_FREE_RATE_DAY_COUNT_DIVISOR
        levels.append(
            levels[-1] + float(closes.iloc[j]) - float(closes.iloc[j - 1]) * (1 + risk_free_rate * fraction)
        )
    return pd.Series(levels, index=index)


def annualization_factor(index: pd.Index) -> int:
    """Infers an annualization factor from the average number of calendar
    days between consecutive observations. Shared by sharpe_ratio here
    and econometrics.volatility/annualize.
    """
    distances = [(index[i] - index[i - 1]).days for i in range(1, len(index))]
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
        f"cannot infer an annualization factor, average distance between observations: {average_distance} days"
    )


def total_return(closes: pd.Series) -> float:
    if len(closes) < 2:
        raise InsufficientDataError(f"total_return needs at least 2 closes, got {len(closes)}")
    if closes.iloc[0] == 0:
        raise InsufficientDataError("total_return got a zero starting close")
    return float((closes.iloc[-1] - closes.iloc[0]) / closes.iloc[0])


def annualized_return(closes: pd.Series, risk_free_rate: float = 0.0) -> float:
    if len(closes) < 2:
        raise InsufficientDataError(f"annualized_return needs at least 2 closes, got {len(closes)}")
    elapsed_days = (closes.index[-1] - closes.index[0]).days
    if elapsed_days <= 0:
        raise InsufficientDataError("timestamps must span a positive number of calendar days")

    levels = _excess_return_levels(closes, risk_free_rate)
    return float((levels.iloc[-1] / levels.iloc[0]) ** (CALENDAR_DAYS_PER_YEAR / elapsed_days) - 1.0)


def max_drawdown(closes: pd.Series) -> float:
    if len(closes) < 2:
        raise InsufficientDataError(f"max_drawdown needs at least 2 closes, got {len(closes)}")
    peak = float(closes.iloc[0])
    worst = 0.0
    for price in closes.iloc[1:]:
        peak = max(peak, float(price))
        if peak == 0:
            continue
        drawdown = (float(price) - peak) / peak
        worst = min(worst, drawdown)
    return worst


def sharpe_ratio(closes: pd.Series, risk_free_rate: float = 0.0) -> float:
    """Annualized excess return over annualized volatility (sample stdev,
    N-1), both derived from real elapsed calendar time, times 100.
    """
    if len(closes) < 3:
        raise InsufficientDataError(f"sharpe_ratio needs at least 3 closes, got {len(closes)}")

    levels = _excess_return_levels(closes, risk_free_rate)
    elapsed_days = (closes.index[-1] - closes.index[0]).days
    if elapsed_days <= 0:
        raise InsufficientDataError("timestamps must span a positive number of calendar days")
    ann_return = (levels.iloc[-1] / levels.iloc[0]) ** (CALENDAR_DAYS_PER_YEAR / elapsed_days) - 1.0

    period_returns = _period_returns(levels)
    if len(period_returns) < 2:
        raise InsufficientDataError(f"sharpe_ratio needs at least 2 valid returns, got {len(period_returns)}")
    sample_stdev = float(period_returns.std())
    if sample_stdev == 0:
        return 0.0
    factor = annualization_factor(closes.index)
    ann_vol_pct = sample_stdev * math.sqrt(factor) * 100.0

    return float(ann_return / ann_vol_pct * 100.0)


def exponential_std_series(returns: pd.Series, beta: float = 0.75) -> pd.Series:
    """Exponentially weighted standard deviation of a returns series,
    matching pandas' ewm(alpha=1-beta, adjust=False).std(). beta must be
    in [0, 1).
    """
    if not (0.0 <= beta < 1.0):
        raise ValueError("beta must be in [0, 1)")
    result: pd.Series = returns.ewm(alpha=1.0 - beta, adjust=False).std()
    return result


def exponential_std(closes: pd.Series, beta: float = 0.75) -> float:
    returns = _period_returns(closes)
    if len(returns) < 2:
        raise InsufficientDataError(f"exponential_std needs at least 2 valid returns, got {len(returns)}")
    return float(exponential_std_series(returns, beta).iloc[-1])
