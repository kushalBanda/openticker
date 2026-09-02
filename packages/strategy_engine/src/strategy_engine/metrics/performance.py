import statistics
from dataclasses import dataclass
from datetime import datetime

TRADING_DAYS_PER_YEAR = 252
DAYS_PER_YEAR = 365


@dataclass(frozen=True)
class PerformanceReport:
    sharpe: float
    max_drawdown: float
    win_rate: float
    cagr: float


def compute_metrics(equity_curve: list[tuple[datetime, float]]) -> PerformanceReport:
    if len(equity_curve) < 2:
        return PerformanceReport(sharpe=0.0, max_drawdown=0.0, win_rate=0.0, cagr=0.0)

    values = [v for _, v in equity_curve]
    returns = [
        (values[i] - values[i - 1]) / values[i - 1] for i in range(1, len(values))
    ]

    return PerformanceReport(
        sharpe=_sharpe(returns),
        max_drawdown=_max_drawdown(values),
        win_rate=_win_rate(returns),
        cagr=_cagr(equity_curve),
    )


def _sharpe(returns: list[float]) -> float:
    std_dev = statistics.pstdev(returns)
    if std_dev == 0:
        return 0.0
    mean_return = statistics.fmean(returns)
    return float((mean_return / std_dev) * (TRADING_DAYS_PER_YEAR**0.5))


def _max_drawdown(values: list[float]) -> float:
    peak = values[0]
    max_dd = 0.0
    for v in values:
        peak = max(peak, v)
        drawdown = (peak - v) / peak if peak > 0 else 0.0
        max_dd = max(max_dd, drawdown)
    return max_dd


def _win_rate(returns: list[float]) -> float:
    # Proxy for trade win rate: fraction of periods with a positive equity
    # change, since only the equity curve (not per-trade fills) is passed in.
    if not returns:
        return 0.0
    wins = sum(1 for r in returns if r > 0)
    return wins / len(returns)


def _cagr(equity_curve: list[tuple[datetime, float]]) -> float:
    start_ts, start_value = equity_curve[0]
    end_ts, end_value = equity_curve[-1]
    days = (end_ts - start_ts).days
    if days <= 0 or start_value <= 0:
        return 0.0
    years = days / DAYS_PER_YEAR
    return float((end_value / start_value) ** (1 / years) - 1)
