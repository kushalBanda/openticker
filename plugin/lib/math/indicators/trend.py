"""Trend indicators: thin, tested wrappers around `ta.trend`. Every
window/step is a keyword parameter using ta's own name and default -
see Task 3's rationale for why this wraps a library instead of
hand-rolling the recursion.
"""

from dataclasses import dataclass

from ta.trend import (
    MACD,
    ADXIndicator,
    EMAIndicator,
    PSARIndicator,
    SMAIndicator,
    WMAIndicator,
)

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
class MacdReading:
    macd: TrailingReading
    signal: TrailingReading
    histogram: TrailingReading


@dataclass(frozen=True)
class AdxReading:
    adx: TrailingReading
    plus_di: TrailingReading
    minus_di: TrailingReading


def compute_sma(bars: list[Bar], window: int = 20, trailing_count: int = DEFAULT_TRAILING_COUNT) -> TrailingReading:
    if len(bars) < window:
        raise InsufficientDataError(f"compute_sma needs at least {window} bars, got {len(bars)}")
    series = SMAIndicator(close=bar_closes_to_series(bars), window=window).sma_indicator()
    return _trailing_reading(series, trailing_count)


def compute_ema(bars: list[Bar], window: int = 20, trailing_count: int = DEFAULT_TRAILING_COUNT) -> TrailingReading:
    if len(bars) < window:
        raise InsufficientDataError(f"compute_ema needs at least {window} bars, got {len(bars)}")
    series = EMAIndicator(close=bar_closes_to_series(bars), window=window).ema_indicator()
    return _trailing_reading(series, trailing_count)


def compute_wma(bars: list[Bar], window: int = 9, trailing_count: int = DEFAULT_TRAILING_COUNT) -> TrailingReading:
    if len(bars) < window:
        raise InsufficientDataError(f"compute_wma needs at least {window} bars, got {len(bars)}")
    series = WMAIndicator(close=bar_closes_to_series(bars), window=window).wma()
    return _trailing_reading(series, trailing_count)


def compute_macd(
    bars: list[Bar], window_slow: int = 26, window_fast: int = 12, window_sign: int = 9,
    trailing_count: int = DEFAULT_TRAILING_COUNT,
) -> MacdReading:
    if len(bars) < window_slow:
        raise InsufficientDataError(f"compute_macd needs at least {window_slow} bars, got {len(bars)}")
    indicator = MACD(close=bar_closes_to_series(bars), window_slow=window_slow, window_fast=window_fast, window_sign=window_sign)
    return MacdReading(
        macd=_trailing_reading(indicator.macd(), trailing_count),
        signal=_trailing_reading(indicator.macd_signal(), trailing_count),
        histogram=_trailing_reading(indicator.macd_diff(), trailing_count),
    )


def compute_adx(bars: list[Bar], window: int = 14, trailing_count: int = DEFAULT_TRAILING_COUNT) -> AdxReading:
    if len(bars) < window * 2:
        raise InsufficientDataError(f"compute_adx needs at least {window * 2} bars, got {len(bars)}")
    indicator = ADXIndicator(high=bar_highs_to_series(bars), low=bar_lows_to_series(bars), close=bar_closes_to_series(bars), window=window)
    return AdxReading(
        adx=_trailing_reading(indicator.adx(), trailing_count),
        plus_di=_trailing_reading(indicator.adx_pos(), trailing_count),
        minus_di=_trailing_reading(indicator.adx_neg(), trailing_count),
    )


def compute_parabolic_sar(
    bars: list[Bar], step: float = 0.02, max_step: float = 0.2, trailing_count: int = DEFAULT_TRAILING_COUNT,
) -> TrailingReading:
    if len(bars) < 3:
        raise InsufficientDataError(f"compute_parabolic_sar needs at least 3 bars, got {len(bars)}")
    indicator = PSARIndicator(high=bar_highs_to_series(bars), low=bar_lows_to_series(bars), close=bar_closes_to_series(bars), step=step, max_step=max_step)
    return _trailing_reading(indicator.psar(), trailing_count)
