"""Turns a fired Trigger into an order. Carries no timing logic - that
belongs to a Trigger (lib.math.triggers).

Ported from strategy.core.action, dropping the Action Protocol
declaration.
"""

from lib.math.broker import BacktestBroker
from lib.math.constants import ORDER_SIDE_BUY, ORDER_SIDE_SELL, ORDER_TYPE_MARKET
from lib.math.models import Order
from lib.math.portfolio import Portfolio
from lib.mechanics.models import Bar


class EnterLongAction:
    """Submits a market buy for quantity shares, unless the symbol
    already has an open position, in which case it no-ops.
    """

    def __init__(self, quantity: int) -> None:
        self._quantity = quantity

    async def execute(self, symbol: str, bar: Bar, portfolio: Portfolio, broker: BacktestBroker) -> None:
        if portfolio.positions.get(symbol, 0) != 0:
            return
        await broker.submit_order(
            Order(symbol=symbol, side=ORDER_SIDE_BUY, quantity=self._quantity, order_type=ORDER_TYPE_MARKET, placed_at_ts=bar.ts)
        )


class ExitLongAction:
    """Submits a market sell for the symbol's full open position, unless
    there is no long position to close.
    """

    async def execute(self, symbol: str, bar: Bar, portfolio: Portfolio, broker: BacktestBroker) -> None:
        position = portfolio.positions.get(symbol, 0)
        if position <= 0:
            return
        await broker.submit_order(
            Order(symbol=symbol, side=ORDER_SIDE_SELL, quantity=position, order_type=ORDER_TYPE_MARKET, placed_at_ts=bar.ts)
        )


class ExitShortAction:
    """Submits a market buy to close the symbol's full open short
    position, unless there is no short position to close.
    """

    async def execute(self, symbol: str, bar: Bar, portfolio: Portfolio, broker: BacktestBroker) -> None:
        position = portfolio.positions.get(symbol, 0)
        if position >= 0:
            return
        await broker.submit_order(
            Order(symbol=symbol, side=ORDER_SIDE_BUY, quantity=abs(position), order_type=ORDER_TYPE_MARKET, placed_at_ts=bar.ts)
        )


class ReverseToLongAction:
    """Submits a market buy sized to close any open short and open a new
    quantity-share long in one order. No-ops if already long quantity
    shares. Portfolio.apply_fills already handles the flip-through-zero
    P&L split, this only sizes the order.
    """

    def __init__(self, quantity: int) -> None:
        self._quantity = quantity

    async def execute(self, symbol: str, bar: Bar, portfolio: Portfolio, broker: BacktestBroker) -> None:
        position = portfolio.positions.get(symbol, 0)
        if position == self._quantity:
            return
        buy_quantity = self._quantity - position
        await broker.submit_order(
            Order(symbol=symbol, side=ORDER_SIDE_BUY, quantity=buy_quantity, order_type=ORDER_TYPE_MARKET, placed_at_ts=bar.ts)
        )


class ReverseToShortAction:
    """Submits a market sell sized to close any open long and open a new
    quantity-share short in one order. No-ops if already short quantity
    shares.
    """

    def __init__(self, quantity: int) -> None:
        self._quantity = quantity

    async def execute(self, symbol: str, bar: Bar, portfolio: Portfolio, broker: BacktestBroker) -> None:
        position = portfolio.positions.get(symbol, 0)
        if position == -self._quantity:
            return
        sell_quantity = position + self._quantity
        await broker.submit_order(
            Order(symbol=symbol, side=ORDER_SIDE_SELL, quantity=sell_quantity, order_type=ORDER_TYPE_MARKET, placed_at_ts=bar.ts)
        )
