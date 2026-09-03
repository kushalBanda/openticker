import math
from dataclasses import dataclass

import numpy as np
from ingest.core.models import Bar
from scipy.stats import spearmanr

from quant.core.constants import MIN_SAMPLE_SIZE, OVERLAPPING_WINDOWS_CAVEAT
from quant.core.exceptions import InsufficientDataError
from quant.core.interfaces import Signal
from quant.evaluation.forward_returns import forward_returns


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


def evaluate_signal(
    signal: Signal,
    bars: list[Bar],
    horizon: int,
    min_lookback: int,
) -> SignalEvaluationReport:
    """Evaluate whether ``signal`` predicts forward returns on ``bars``.

    Args:
        signal: the signal instance to evaluate, already constructed
            (e.g. via SignalFactory).
        bars: bars sorted ascending by timestamp, already fetched by the
            caller.
        horizon: number of bars ahead to measure the forward return over.
        min_lookback: smallest window ``signal.compute()`` needs to
            produce a valid value (e.g. period + 1 for RSI). Caller's
            responsibility, not inferred from the signal.

    Returns:
        A SignalEvaluationReport.

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
        raw = signal.compute(bars[i - min_lookback + 1 : i + 1])
        signal_values.append(raw.value)
        return_values.append(forward_return)

    sample_size = len(signal_values)
    if sample_size < MIN_SAMPLE_SIZE:
        raise InsufficientDataError(
            f"only {sample_size} valid (signal, forward return) pairs, "
            f"need at least {MIN_SAMPLE_SIZE}"
        )

    signal_array = np.array(signal_values)
    return_array = np.array(return_values)

    ic_result = spearmanr(signal_array, return_array)
    ic = float(ic_result.statistic)
    ic_p_value = float(ic_result.pvalue)
    if math.isnan(ic):
        raise InsufficientDataError(
            "information coefficient is undefined: signal or forward "
            "return values are constant across the sample"
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
        raise InsufficientDataError(
            "turnover proxy is undefined: signal value is constant "
            "across the sample"
        )
    turnover_proxy = 1 - autocorrelation

    return SignalEvaluationReport(
        signal_name=signal.name,
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
