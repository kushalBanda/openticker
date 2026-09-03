from collections import deque

from ingest.core.models import Bar
from quant.signals.sma.signal import SmaSignal

from strategy.core.constants import (
    ORDER_SIDE_BUY,
    ORDER_SIDE_SELL,
    ORDER_TYPE_MARKET,
)
from strategy.core.interfaces import Broker
from strategy.core.models import Order
from strategy.core.portfolio import Portfolio
from strategy.core.registry import register_strategy


@register_strategy("sma_crossover")
class SmaCrossoverStrategy:
    def __init__(self, short_window: int, long_window: int, quantity: int) -> None:
        if short_window >= long_window:
            raise ValueError("short_window must be less than long_window")
        self._short_window = short_window
        self._long_window = long_window
        self._quantity = quantity
        self._bars: dict[str, deque[Bar]] = {}
        self._short_signal = SmaSignal(window=short_window)
        self._long_signal = SmaSignal(window=long_window)
        self._was_short_above_long: dict[str, bool] = {}

    async def on_bar(self, bars: dict[str, Bar], portfolio: Portfolio, broker: Broker) -> None:
        for symbol, bar in bars.items():
            await self._on_symbol_bar(symbol, bar, portfolio, broker)

    async def _on_symbol_bar(
        self, symbol: str, bar: Bar, portfolio: Portfolio, broker: Broker
    ) -> None:
        history = self._bars.setdefault(symbol, deque(maxlen=self._long_window))
        history.append(bar)
        if len(history) < self._long_window:
            return

        symbol_bars = list(history)
        short_sma = self._short_signal.compute(symbol_bars).value
        long_sma = self._long_signal.compute(symbol_bars).value
        is_short_above_long = short_sma > long_sma

        was_short_above_long = self._was_short_above_long.get(symbol)
        if was_short_above_long is not None:
            crossed_up = is_short_above_long and not was_short_above_long
            crossed_down = not is_short_above_long and was_short_above_long
            position = portfolio.positions.get(symbol, 0)

            if crossed_up and position == 0:
                await broker.submit_order(
                    Order(
                        symbol=symbol,
                        side=ORDER_SIDE_BUY,
                        quantity=self._quantity,
                        order_type=ORDER_TYPE_MARKET,
                        placed_at_ts=bar.ts,
                    )
                )
            elif crossed_down and position > 0:
                await broker.submit_order(
                    Order(
                        symbol=symbol,
                        side=ORDER_SIDE_SELL,
                        quantity=position,
                        order_type=ORDER_TYPE_MARKET,
                        placed_at_ts=bar.ts,
                    )
                )

        self._was_short_above_long[symbol] = is_short_above_long
