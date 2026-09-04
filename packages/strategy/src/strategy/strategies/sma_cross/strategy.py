from collections import deque

from ingest.core.models import Bar
from quant.signals.sma.signal import SmaSignal

from strategy.core.action import ReverseToLongAction, ReverseToShortAction
from strategy.core.interfaces import Broker
from strategy.core.portfolio import Portfolio
from strategy.core.registry import register_strategy
from strategy.core.trigger import CrossoverTrigger


@register_strategy("sma_cross")
class SmaCrossStrategy:
    """Always-in-the-market SMA crossover.Golden cross (fast crosses above slow) flips to long `quantity` shares, 
    death cross (fast crosses below slow) flips to short `quantity` shares, 
    unlike `sma_crossover` (removed), this never sits flat.
    """

    def __init__(self, short_window: int, long_window: int, quantity: int) -> None:
        if short_window >= long_window:
            raise ValueError("short_window must be less than long_window")
        self._long_window = long_window
        self._bars: dict[str, deque[Bar]] = {}

        fast_signal = SmaSignal(window=short_window)
        slow_signal = SmaSignal(window=long_window)
        self._golden_cross_trigger = CrossoverTrigger(
            fast=fast_signal, slow=slow_signal, direction="up", min_bars=long_window
        )
        self._death_cross_trigger = CrossoverTrigger(
            fast=fast_signal, slow=slow_signal, direction="down", min_bars=long_window
        )
        self._go_long = ReverseToLongAction(quantity=quantity)
        self._go_short = ReverseToShortAction(quantity=quantity)

    async def on_bar(self, bars: dict[str, Bar], portfolio: Portfolio, broker: Broker) -> None:
        for symbol, bar in bars.items():
            await self._on_symbol_bar(symbol, bar, portfolio, broker)

    async def _on_symbol_bar(
        self, symbol: str, bar: Bar, portfolio: Portfolio, broker: Broker
    ) -> None:
        history = self._bars.setdefault(symbol, deque(maxlen=self._long_window))
        history.append(bar)
        symbol_bars = list(history)

        # Both triggers checked every bar (not short-circuited), each keeps
        # its own fast-vs-slow baseline internally, an unchecked trigger
        # would go stale and misfire on the next flip.
        golden_cross = self._golden_cross_trigger.check(symbol, symbol_bars)
        death_cross = self._death_cross_trigger.check(symbol, symbol_bars)
        if golden_cross:
            await self._go_long.execute(symbol, bar, portfolio, broker)
        elif death_cross:
            await self._go_short.execute(symbol, bar, portfolio, broker)
