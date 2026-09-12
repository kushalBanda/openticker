"""Does a signal predict forward returns? Information coefficient, its
p-value, and a turnover proxy, computed on real bars.

Ported verbatim from quant.evaluation.{evaluator,forward_returns} - both
were already flat module-level functions plus one dataclass, no registry
involved.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
from scipy.stats import spearmanr

from lib.math.constants import MIN_SAMPLE_SIZE, OVERLAPPING_WINDOWS_CAVEAT
from lib.math.exceptions import InsufficientDataError
from lib.math.types import RawSignal
from lib.mechanics.models import Bar


@dataclass(frozen=True)
class SignalEvaluationReport:
    signal_name: str
    symbol: str
    interval: str
    horizon: int
    sample_size: int
    effective_sample_size: int
    information_coefficient: float
    ic_p_value: float
    effective_ic_p_value: float
    turnover_proxy: float
    overlapping_windows_caveat: str


def forward_returns(bars: list[Bar], horizon: int) -> list[float | None]:
    """The N-day forward return for every bar: close[i+horizon]/close[i] - 1.

    The last `horizon` entries are None since no future bar exists yet.
    """
    if horizon <= 0:
        raise ValueError("horizon must be greater than 0")

    returns: list[float | None] = []
    last_valid_index = len(bars) - horizon
    for i, bar in enumerate(bars):
        if i >= last_valid_index:
            returns.append(None)
            continue
        future_close = bars[i + horizon].close
        returns.append(future_close / bar.close - 1)
    return returns


def evaluate_signal_ic(
    compute: Callable[[list[Bar]], RawSignal],
    signal_name: str,
    bars: list[Bar],
    horizon: int,
    min_lookback: int,
) -> SignalEvaluationReport:
    """Evaluate whether a signal's compute function predicts forward returns.

    Args:
        compute: a windowed-bars-in, RawSignal-out function, e.g.
            `lambda window: compute_rsi(window, period=14)`.
        signal_name: name to stamp on the resulting report.
        bars: bars sorted ascending by timestamp.
        horizon: number of bars ahead to measure the forward return over.
        min_lookback: smallest window `compute` needs to produce a valid
            value (e.g. period + 1 for RSI). Caller's responsibility.

    Raises:
        InsufficientDataError: fewer than MIN_SAMPLE_SIZE valid (signal,
            forward return) pairs result after windowing, or either
            correlation is undefined (constant input).
    """
    returns = forward_returns(bars, horizon)

    signal_values: list[float] = []
    return_values: list[float] = []
    for i in range(min_lookback - 1, len(bars)):
        forward_return = returns[i]
        if forward_return is None:
            continue
        raw = compute(bars[i - min_lookback + 1 : i + 1])
        signal_values.append(raw.value)
        return_values.append(forward_return)

    sample_size = len(signal_values)
    if sample_size < MIN_SAMPLE_SIZE:
        raise InsufficientDataError(
            f"only {sample_size} valid (signal, forward return) pairs, need at least {MIN_SAMPLE_SIZE}"
        )

    signal_array = np.array(signal_values)
    return_array = np.array(return_values)

    ic_result = spearmanr(signal_array, return_array)
    ic = float(ic_result.statistic)
    ic_p_value = float(ic_result.pvalue)
    if math.isnan(ic):
        raise InsufficientDataError(
            "information coefficient is undefined: signal or forward return values are constant across the sample"
        )

    effective_signal = signal_array[::horizon]
    effective_returns = return_array[::horizon]
    effective_sample_size = len(effective_signal)
    if effective_sample_size < 2:
        effective_ic_p_value = float("nan")
    else:
        effective_result = spearmanr(effective_signal, effective_returns)
        effective_ic_p_value = float(effective_result.pvalue)

    if sample_size < 2:
        autocorrelation = float("nan")
    else:
        corr_matrix = np.corrcoef(signal_array[:-1], signal_array[1:])
        autocorrelation = float(corr_matrix[0, 1])
    if math.isnan(autocorrelation):
        raise InsufficientDataError("turnover proxy is undefined: signal value is constant across the sample")
    turnover_proxy = 1 - autocorrelation

    return SignalEvaluationReport(
        signal_name=signal_name,
        symbol=bars[-1].symbol,
        interval=bars[-1].interval,
        horizon=horizon,
        sample_size=sample_size,
        effective_sample_size=effective_sample_size,
        information_coefficient=ic,
        ic_p_value=ic_p_value,
        effective_ic_p_value=effective_ic_p_value,
        turnover_proxy=turnover_proxy,
        overlapping_windows_caveat=OVERLAPPING_WINDOWS_CAVEAT,
    )
