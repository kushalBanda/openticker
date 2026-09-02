from collections import deque

from data_engine.core.models import Bar

from strategy_engine.core.constants import (
    ORDER_SIDE_BUY,
    ORDER_SIDE_SELL,
    ORDER_TYPE_MARKET,
)
from strategy_engine.core.interfaces import Broker
from strategy_engine.core.models import Order
from strategy_engine.core.portfolio import Portfolio
from strategy_engine.core.registry import register_strategy


@register_strategy("sma_crossover")
class SmaCrossoverStrategy:
    def __init__(self, short_window: int, long_window: int, quantity: int) -> None:
        if short_window >= long_window:
            raise ValueError("short_window must be less than long_window")
        self._short_window = short_window
        self._long_window = long_window
        self._quantity = quantity
        self._closes: deque[float] = deque(maxlen=long_window)
        self._was_short_above_long: bool | None = None

    def on_bar(self, bar: Bar, portfolio: Portfolio, broker: Broker) -> None:
        self._closes.append(bar.close)
        if len(self._closes) < self._long_window:
            return

        short_sma = sum(list(self._closes)[-self._short_window :]) / self._short_window
        long_sma = sum(self._closes) / self._long_window
        is_short_above_long = short_sma > long_sma

        if self._was_short_above_long is not None:
            crossed_up = is_short_above_long and not self._was_short_above_long
            crossed_down = not is_short_above_long and self._was_short_above_long
            position = portfolio.positions.get(bar.symbol, 0)

            if crossed_up and position == 0:
                broker.submit_order(
                    Order(
                        symbol=bar.symbol,
                        side=ORDER_SIDE_BUY,
                        quantity=self._quantity,
                        order_type=ORDER_TYPE_MARKET,
                        placed_at_ts=bar.ts,
                    )
                )
            elif crossed_down and position > 0:
                broker.submit_order(
                    Order(
                        symbol=bar.symbol,
                        side=ORDER_SIDE_SELL,
                        quantity=position,
                        order_type=ORDER_TYPE_MARKET,
                        placed_at_ts=bar.ts,
                    )
                )

        self._was_short_above_long = is_short_above_long
