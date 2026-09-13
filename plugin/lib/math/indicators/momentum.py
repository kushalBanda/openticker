"""Momentum indicators: thin, tested wrappers around `ta.momentum` (and
`ta.trend.CCIIndicator`, which ta itself files under trend). Every
window/constant is a keyword parameter using ta's own name and default.
"""

from dataclasses import dataclass

from ta.momentum import (
    ROCIndicator,
    RSIIndicator,
    StochasticOscillator,
    StochRSIIndicator,
    WilliamsRIndicator,
)
from ta.trend import CCIIndicator

from lib.math.exceptions import InsufficientDataError
from lib.math.indicators._common import (
    DEFAULT_TRAILING_COUNT,
    TrailingReading,
    _trailing_reading,
)
from lib.math.series import (
    bar_closes_to_series,
    bar_highs_to_series,
    bar_lows_to_series,
)
from lib.mechanics.models import Bar


@dataclass(frozen=True)
class StochasticReading:
    k: TrailingReading
    d: TrailingReading


@dataclass(frozen=True)
class StochasticRsiReading:
    stochrsi: TrailingReading
    k: TrailingReading
    d: TrailingReading


def compute_rsi(bars: list[Bar], window: int = 14, trailing_count: int = DEFAULT_TRAILING_COUNT) -> TrailingReading:
    if len(bars) < window + 1:
        raise InsufficientDataError(f"compute_rsi needs at least {window + 1} bars, got {len(bars)}")
    series = RSIIndicator(close=bar_closes_to_series(bars), window=window).rsi()
    return _trailing_reading(series, trailing_count)


def compute_stochastic(
    bars: list[Bar], window: int = 14, smooth_window: int = 3, trailing_count: int = DEFAULT_TRAILING_COUNT,
) -> StochasticReading:
    if len(bars) < window + smooth_window:
        raise InsufficientDataError(f"compute_stochastic needs at least {window + smooth_window} bars, got {len(bars)}")
    indicator = StochasticOscillator(
        high=bar_highs_to_series(bars), low=bar_lows_to_series(bars), close=bar_closes_to_series(bars),
        window=window, smooth_window=smooth_window,
    )
    return StochasticReading(
        k=_trailing_reading(indicator.stoch(), trailing_count),
        d=_trailing_reading(indicator.stoch_signal(), trailing_count),
    )


def compute_stochastic_rsi(
    bars: list[Bar], window: int = 14, smooth1: int = 3, smooth2: int = 3, trailing_count: int = DEFAULT_TRAILING_COUNT,
) -> StochasticRsiReading:
    if len(bars) < window * 2:
        raise InsufficientDataError(f"compute_stochastic_rsi needs at least {window * 2} bars, got {len(bars)}")
    indicator = StochRSIIndicator(close=bar_closes_to_series(bars), window=window, smooth1=smooth1, smooth2=smooth2)
    return StochasticRsiReading(
        stochrsi=_trailing_reading(indicator.stochrsi(), trailing_count),
        k=_trailing_reading(indicator.stochrsi_k(), trailing_count),
        d=_trailing_reading(indicator.stochrsi_d(), trailing_count),
    )


def compute_williams_r(bars: list[Bar], lbp: int = 14, trailing_count: int = DEFAULT_TRAILING_COUNT) -> TrailingReading:
    if len(bars) < lbp:
        raise InsufficientDataError(f"compute_williams_r needs at least {lbp} bars, got {len(bars)}")
    series = WilliamsRIndicator(high=bar_highs_to_series(bars), low=bar_lows_to_series(bars), close=bar_closes_to_series(bars), lbp=lbp).williams_r()
    return _trailing_reading(series, trailing_count)


def compute_roc(bars: list[Bar], window: int = 12, trailing_count: int = DEFAULT_TRAILING_COUNT) -> TrailingReading:
    if len(bars) <= window:
        raise InsufficientDataError(f"compute_roc needs more than {window} bars, got {len(bars)}")
    series = ROCIndicator(close=bar_closes_to_series(bars), window=window).roc()
    return _trailing_reading(series, trailing_count)


def compute_cci(bars: list[Bar], window: int = 20, constant: float = 0.015, trailing_count: int = DEFAULT_TRAILING_COUNT) -> TrailingReading:
    if len(bars) < window:
        raise InsufficientDataError(f"compute_cci needs at least {window} bars, got {len(bars)}")
    series = CCIIndicator(high=bar_highs_to_series(bars), low=bar_lows_to_series(bars), close=bar_closes_to_series(bars), window=window, constant=constant).cci()
    return _trailing_reading(series, trailing_count)
