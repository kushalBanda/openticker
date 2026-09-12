"""Answers one question per trigger: has the condition it watches for
happened on this bar. Carries no order-side logic - that belongs to an
Action (lib.math.actions).

Ported from strategy.core.trigger, dropping the Trigger Protocol
declaration (Python does not need it to duck-type) and the Signal
Protocol parameter - a "signal" here is just a plain
Callable[[list[Bar]], RawSignal], the same shape lib.math.indicators'
compute_* functions produce when partially applied with their params.
"""

from collections.abc import Callable
from typing import Literal

from lib.math.series import bar_closes_to_series
from lib.math.technicals import bollinger_bands, relative_strength_index
from lib.math.types import RawSignal
from lib.mechanics.models import Bar

SignalFn = Callable[[list[Bar]], RawSignal]


class CrossoverTrigger:
    """Fires once on the bar where fast crosses slow in direction.

    Tracks each symbol's last known fast-vs-slow relation internally, so
    it fires only on the bar the relation actually flips. Needs at least
    min_bars bars before it starts checking.
    """

    def __init__(self, fast: SignalFn, slow: SignalFn, direction: Literal["up", "down"], min_bars: int) -> None:
        self._fast = fast
        self._slow = slow
        self._direction = direction
        self._min_bars = min_bars
        self._was_fast_above_slow: dict[str, bool] = {}

    def check(self, symbol: str, bars: list[Bar]) -> bool:
        if len(bars) < self._min_bars:
            return False

        fast_value = self._fast(bars).value
        slow_value = self._slow(bars).value
        is_fast_above_slow = fast_value > slow_value

        was_fast_above_slow = self._was_fast_above_slow.get(symbol)
        self._was_fast_above_slow[symbol] = is_fast_above_slow

        if was_fast_above_slow is None:
            return False
        if self._direction == "up":
            return is_fast_above_slow and not was_fast_above_slow
        return (not is_fast_above_slow) and was_fast_above_slow


class ThresholdTrigger:
    """Fires while signal's value crosses past level in direction. No
    edge-detection, unlike CrossoverTrigger - fires every bar the
    condition holds.
    """

    def __init__(self, signal: SignalFn, level: float, direction: Literal["above", "below"]) -> None:
        self._signal = signal
        self._level = level
        self._direction = direction

    def check(self, symbol: str, bars: list[Bar]) -> bool:
        value = self._signal(bars).value
        if self._direction == "above":
            return value > self._level
        return value < self._level


class BollingerRsiEntryTrigger:
    """Fires on a Bollinger Band mean-reversion entry, ported from
    nautilus_trader's BBMeanReversion: direction="long" fires when price
    closes at/below the lower band while RSI confirms oversold
    (rsi < rsi_threshold); direction="short" fires when price closes
    at/above the upper band while RSI confirms overbought
    (rsi > rsi_threshold). RSI is on this repo's 0..100 scale, not
    nautilus's own 0..1 scale - thresholds are not interchangeable.
    """

    def __init__(
        self,
        bb_window: int,
        bb_std: float,
        rsi_period: int,
        rsi_threshold: float,
        direction: Literal["long", "short"],
    ) -> None:
        self._bb_window = bb_window
        self._bb_std = bb_std
        self._rsi_period = rsi_period
        self._rsi_threshold = rsi_threshold
        self._direction = direction
        self._min_bars = max(bb_window, rsi_period + 1)

    def check(self, symbol: str, bars: list[Bar]) -> bool:
        if len(bars) < self._min_bars:
            return False

        closes = bar_closes_to_series(bars)
        bands = bollinger_bands(closes, window=self._bb_window, k=self._bb_std)
        rsi = relative_strength_index(closes, self._rsi_period)

        close = closes.iloc[-1]
        rsi_value = rsi.iloc[-1]
        if self._direction == "long":
            lower = bands["lower"].iloc[-1]
            return bool(close <= lower and rsi_value < self._rsi_threshold)
        upper = bands["upper"].iloc[-1]
        return bool(close >= upper and rsi_value > self._rsi_threshold)
