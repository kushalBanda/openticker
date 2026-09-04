from typing import Literal, Protocol

from ingest.core.models import Bar
from quant.core.interfaces import Signal


class Trigger(Protocol):
    """Answers one question: has the condition this trigger watches for
    happened on this bar. Carries no order-side logic — that belongs to
    an `Action` (see `strategy.core.action`), kept separate on purpose so
    entry/exit conditions can change without touching order generation.
    """

    def check(self, symbol: str, bars: list[Bar]) -> bool: ...


class CrossoverTrigger:
    """Fires once on the bar where `fast` crosses `slow` in `direction`.

    Tracks each symbol's last known fast-vs-slow relation internally, so
    it fires only on the bar the relation actually flips, not on every
    bar where fast happens to stay above/below slow. Needs at least
    `min_bars` bars before it starts checking, so callers with a shorter
    history never spuriously "flip" from an unset baseline.
    """

    def __init__(
        self,
        fast: Signal,
        slow: Signal,
        direction: Literal["up", "down"],
        min_bars: int,
    ) -> None:
        self._fast = fast
        self._slow = slow
        self._direction = direction
        self._min_bars = min_bars
        self._was_fast_above_slow: dict[str, bool] = {}

    def check(self, symbol: str, bars: list[Bar]) -> bool:
        if len(bars) < self._min_bars:
            return False

        fast_value = self._fast.compute(bars).value
        slow_value = self._slow.compute(bars).value
        is_fast_above_slow = fast_value > slow_value

        was_fast_above_slow = self._was_fast_above_slow.get(symbol)
        self._was_fast_above_slow[symbol] = is_fast_above_slow

        if was_fast_above_slow is None:
            return False
        if self._direction == "up":
            return is_fast_above_slow and not was_fast_above_slow
        return (not is_fast_above_slow) and was_fast_above_slow


class ThresholdTrigger:
    """Fires while `signal`'s value crosses past `level` in `direction`.

    `direction="above"` fires when the value is greater than `level`,
    `direction="below"` fires when it is less than `level`. Unlike
    `CrossoverTrigger` this has no edge-detection, it fires on every bar
    the condition holds, not just the bar it first became true.
    """

    def __init__(self, signal: Signal, level: float, direction: Literal["above", "below"]) -> None:
        self._signal = signal
        self._level = level
        self._direction = direction

    def check(self, symbol: str, bars: list[Bar]) -> bool:
        value = self._signal.compute(bars).value
        if self._direction == "above":
            return value > self._level
        return value < self._level
