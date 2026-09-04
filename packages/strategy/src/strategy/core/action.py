from typing import Protocol

from ingest.core.models import Bar

from strategy.core.constants import (
    ORDER_SIDE_BUY,
    ORDER_SIDE_SELL,
    ORDER_TYPE_MARKET,
)
from strategy.core.interfaces import Broker
from strategy.core.models import Order
from strategy.core.portfolio import Portfolio


class Action(Protocol):
    """Turns a fired `Trigger` into an order. Carries no timing logic —
    that belongs to a `Trigger` (see `strategy.core.trigger`), kept
    separate so order-generation can change without touching entry/exit
    conditions.
    """

    async def execute(self, symbol: str, bar: Bar, portfolio: Portfolio, broker: Broker) -> None: ...


class EnterLongAction:
    """Submits a market buy for `quantity` shares, unless the symbol
    already has an open position, in which case it no-ops.
    """

    def __init__(self, quantity: int) -> None:
        self._quantity = quantity

    async def execute(self, symbol: str, bar: Bar, portfolio: Portfolio, broker: Broker) -> None:
        if portfolio.positions.get(symbol, 0) != 0:
            return
        await broker.submit_order(
            Order(
                symbol=symbol,
                side=ORDER_SIDE_BUY,
                quantity=self._quantity,
                order_type=ORDER_TYPE_MARKET,
                placed_at_ts=bar.ts,
            )
        )


class ExitLongAction:
    """Submits a market sell for the symbol's full open position, unless
    there is no long position to close, in which case it no-ops.
    """

    async def execute(self, symbol: str, bar: Bar, portfolio: Portfolio, broker: Broker) -> None:
        position = portfolio.positions.get(symbol, 0)
        if position <= 0:
            return
        await broker.submit_order(
            Order(
                symbol=symbol,
                side=ORDER_SIDE_SELL,
                quantity=position,
                order_type=ORDER_TYPE_MARKET,
                placed_at_ts=bar.ts,
            )
        )
