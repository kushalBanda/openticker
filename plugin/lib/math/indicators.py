"""Flat signal computations, one function per signal, plus its forecast
scaling.

Ported from quant.signals.{rsi,sma,above_average_volume,time_series_momentum}
.signal - each was a class with a compute()/scale() pair and a
@register_signal decorator. Flattened here into two plain functions per
signal (compute_<name>, scale_<name>), dispatched by name in a skill
script's own dict, no registry lookup.
"""

from lib.math.constants import FORECAST_SCALE_MAX, RSI_MIDPOINT
from lib.math.exceptions import InsufficientDataError
from lib.math.series import bar_closes_to_series, bar_volumes_to_series
from lib.math.technicals import moving_average, relative_strength_index
from lib.math.types import Forecast, RawSignal
from lib.mechanics.models import Bar


def compute_rsi(bars: list[Bar], period: int) -> RawSignal:
    if period <= 0:
        raise ValueError("period must be greater than 0")
    closes = bar_closes_to_series(bars)
    value = float(relative_strength_index(closes, period).iloc[-1])
    last = bars[-1]
    return RawSignal(symbol=last.symbol, interval=last.interval, ts=last.ts, name="rsi", value=value)


def scale_rsi(raw: RawSignal) -> Forecast:
    scaled = (raw.value - RSI_MIDPOINT) * (FORECAST_SCALE_MAX / RSI_MIDPOINT)
    return Forecast(symbol=raw.symbol, interval=raw.interval, ts=raw.ts, name=raw.name, scaled_value=scaled)


def compute_sma(bars: list[Bar], window: int) -> RawSignal:
    if window <= 0:
        raise ValueError("window must be greater than 0")
    closes = bar_closes_to_series(bars)
    value = float(moving_average(closes, window).iloc[-1])
    last = bars[-1]
    return RawSignal(symbol=last.symbol, interval=last.interval, ts=last.ts, name="sma", value=value)


def scale_sma(raw: RawSignal) -> Forecast:
    # A moving average is a raw price level, not a bounded ratio like
    # RSI's 0..100 range - documented pass-through, not a real scale.
    return Forecast(symbol=raw.symbol, interval=raw.interval, ts=raw.ts, name=raw.name, scaled_value=raw.value)


def compute_above_average_volume(bars: list[Bar], window: int) -> RawSignal:
    if window <= 0:
        raise ValueError("window must be greater than 0")
    volumes = bar_volumes_to_series(bars[:-1])
    baseline = float(moving_average(volumes, window).iloc[-1])
    last = bars[-1]
    value = (last.volume / baseline) - 1 if baseline != 0 else 0.0
    return RawSignal(
        symbol=last.symbol, interval=last.interval, ts=last.ts, name="above_average_volume", value=value
    )


def scale_above_average_volume(raw: RawSignal) -> Forecast:
    # Already a bounded ratio (volume/baseline - 1), documented
    # pass-through, same as scale_sma.
    return Forecast(symbol=raw.symbol, interval=raw.interval, ts=raw.ts, name=raw.name, scaled_value=raw.value)


def compute_time_series_momentum(bars: list[Bar], window: int) -> RawSignal:
    """Moskowitz, Ooi & Pedersen (2012): sign of the trailing window-bar
    return, +1.0/-1.0/0.0 - every consumer only ever needs the sign.
    """
    if window <= 0:
        raise ValueError("window must be greater than 0")
    if len(bars) < window + 1:
        raise InsufficientDataError(f"time_series_momentum needs at least {window + 1} bars, got {len(bars)}")
    closes = bar_closes_to_series(bars)
    trailing_return = float(closes.iloc[-1] / closes.iloc[-1 - window] - 1)
    value = 0.0 if trailing_return == 0 else (1.0 if trailing_return > 0 else -1.0)
    last = bars[-1]
    return RawSignal(
        symbol=last.symbol, interval=last.interval, ts=last.ts, name="time_series_momentum", value=value
    )


def scale_time_series_momentum(raw: RawSignal) -> Forecast:
    # Sign is already full conviction, scale straight to the extremes.
    return Forecast(
        symbol=raw.symbol, interval=raw.interval, ts=raw.ts, name=raw.name, scaled_value=raw.value * FORECAST_SCALE_MAX
    )
