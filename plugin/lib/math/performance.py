"""Backtest performance metrics off a finished Portfolio's equity curve.

Ported verbatim from strategy.metrics.performance.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Final

import pandas as pd

from lib.math import statistics

MIN_EQUITY_POINTS_FOR_FULL_REPORT: Final = 3


@dataclass(frozen=True)
class PerformanceReport:
    total_return: float
    annualized_return: float
    max_drawdown: float
    sharpe_ratio: float
    exponential_std: float
    win_rate: float


def compute_metrics(equity_curve: list[tuple[datetime, float]]) -> PerformanceReport:
    if len(equity_curve) < MIN_EQUITY_POINTS_FOR_FULL_REPORT:
        return PerformanceReport(
            total_return=0.0,
            annualized_return=0.0,
            max_drawdown=0.0,
            sharpe_ratio=0.0,
            exponential_std=0.0,
            win_rate=0.0,
        )

    timestamps = [ts for ts, _ in equity_curve]
    values = [v for _, v in equity_curve]
    series = pd.Series(values, index=pd.DatetimeIndex(timestamps), dtype=float)

    return PerformanceReport(
        total_return=statistics.total_return(series),
        annualized_return=statistics.annualized_return(series),
        max_drawdown=statistics.max_drawdown(series),
        sharpe_ratio=statistics.sharpe_ratio(series),
        exponential_std=statistics.exponential_std(series),
        win_rate=_win_rate(values),
    )


def _win_rate(values: list[float]) -> float:
    returns = [
        (values[i] - values[i - 1]) / values[i - 1]
        for i in range(1, len(values))
        if values[i - 1] != 0
    ]
    if not returns:
        return 0.0
    wins = sum(1 for r in returns if r > 0)
    return wins / len(returns)
