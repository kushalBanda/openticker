"""Cross-sectional indicators: relative strength, correlation, beta,
pairs spread. Each takes two aligned bar series (symbol plus benchmark
or pair) - the caller aligns them by timestamp before calling in.
"""

import math
from dataclasses import dataclass

from lib.math.exceptions import InsufficientDataError
from lib.mechanics.models import Bar


@dataclass(frozen=True)
class PairsSpreadReading:
    spread: float
    zscore: float


def _returns(closes: list[float]) -> list[float]:
    return [(closes[i] - closes[i - 1]) / closes[i - 1] for i in range(1, len(closes))]


def compute_relative_strength(bars: list[Bar], benchmark_bars: list[Bar], period: int = 20) -> float:
    if len(bars) <= period or len(benchmark_bars) <= period:
        raise InsufficientDataError(f"compute_relative_strength needs more than {period} bars in both series")
    symbol_ratio = bars[-1].close / bars[-1 - period].close
    benchmark_ratio = benchmark_bars[-1].close / benchmark_bars[-1 - period].close
    return symbol_ratio / benchmark_ratio * 100


def compute_correlation(bars_a: list[Bar], bars_b: list[Bar], period: int = 20) -> float:
    if len(bars_a) < period + 1 or len(bars_b) < period + 1:
        raise InsufficientDataError(f"compute_correlation needs at least {period + 1} bars in both series")
    returns_a = _returns([b.close for b in bars_a[-(period + 1):]])
    returns_b = _returns([b.close for b in bars_b[-(period + 1):]])
    mean_a = sum(returns_a) / len(returns_a)
    mean_b = sum(returns_b) / len(returns_b)
    cov = sum((a - mean_a) * (b - mean_b) for a, b in zip(returns_a, returns_b, strict=True))
    std_a = sum((a - mean_a) ** 2 for a in returns_a) ** 0.5
    std_b = sum((b - mean_b) ** 2 for b in returns_b) ** 0.5
    if std_a == 0 or std_b == 0:
        return 0.0
    return float(cov / (std_a * std_b))


def compute_beta(bars: list[Bar], benchmark_bars: list[Bar], period: int = 60) -> float:
    if len(bars) < period + 1 or len(benchmark_bars) < period + 1:
        raise InsufficientDataError(f"compute_beta needs at least {period + 1} bars in both series")
    returns = _returns([b.close for b in bars[-(period + 1):]])
    bench_returns = _returns([b.close for b in benchmark_bars[-(period + 1):]])
    mean_r = sum(returns) / len(returns)
    mean_b = sum(bench_returns) / len(bench_returns)
    cov = sum((r - mean_r) * (b - mean_b) for r, b in zip(returns, bench_returns, strict=True))
    var_b = sum((b - mean_b) ** 2 for b in bench_returns)
    if var_b == 0:
        raise ValueError("benchmark has zero variance over this window; beta is undefined")
    return cov / var_b


def compute_pairs_spread(bars_a: list[Bar], bars_b: list[Bar], lookback: int = 60, hedge_ratio: float = 1.0) -> PairsSpreadReading:
    if len(bars_a) < lookback or len(bars_b) < lookback:
        raise InsufficientDataError(f"compute_pairs_spread needs at least {lookback} bars in both series")
    window_a, window_b = bars_a[-lookback:], bars_b[-lookback:]
    spreads = [math.log(a.close) - hedge_ratio * math.log(b.close) for a, b in zip(window_a, window_b, strict=True)]
    mean = sum(spreads) / len(spreads)
    variance = sum((s - mean) ** 2 for s in spreads) / len(spreads)
    std = variance ** 0.5
    current_spread = spreads[-1]
    zscore = 0.0 if std == 0 else (current_spread - mean) / std
    return PairsSpreadReading(spread=current_spread, zscore=zscore)
