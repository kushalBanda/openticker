from collections import deque

from ingest.core.models import Bar
from quant.signals.sma.signal import SmaSignal

from strategy.core.action import EnterLongAction, ExitLongAction
from strategy.core.interfaces import Broker
from strategy.core.portfolio import Portfolio
from strategy.core.registry import register_strategy
from strategy.core.trigger import CrossoverTrigger


@register_strategy("sma_crossover")
class SmaCrossoverStrategy:
    def __init__(self, short_window: int, long_window: int, quantity: int) -> None:
        if short_window >= long_window:
            raise ValueError("short_window must be less than long_window")
        self._long_window = long_window
        self._bars: dict[str, deque[Bar]] = {}

        fast_signal = SmaSignal(window=short_window)
        slow_signal = SmaSignal(window=long_window)
        self._entry_trigger = CrossoverTrigger(
            fast=fast_signal, slow=slow_signal, direction="up", min_bars=long_window
        )
        self._exit_trigger = CrossoverTrigger(
            fast=fast_signal, slow=slow_signal, direction="down", min_bars=long_window
        )
        self._enter_action = EnterLongAction(quantity=quantity)
        self._exit_action = ExitLongAction()

    async def on_bar(self, bars: dict[str, Bar], portfolio: Portfolio, broker: Broker) -> None:
        for symbol, bar in bars.items():
            await self._on_symbol_bar(symbol, bar, portfolio, broker)

    async def _on_symbol_bar(
        self, symbol: str, bar: Bar, portfolio: Portfolio, broker: Broker
    ) -> None:
        history = self._bars.setdefault(symbol, deque(maxlen=self._long_window))
        history.append(bar)
        symbol_bars = list(history)

        # Both triggers must be checked every bar (not short-circuited),
        # since each keeps its own fast-vs-slow baseline internally, an
        # unchecked trigger would go stale and misfire on the next flip.
        entry_fired = self._entry_trigger.check(symbol, symbol_bars)
        exit_fired = self._exit_trigger.check(symbol, symbol_bars)
        if entry_fired:
            await self._enter_action.execute(symbol, bar, portfolio, broker)
        elif exit_fired:
            await self._exit_action.execute(symbol, bar, portfolio, broker)
