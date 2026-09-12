"""Buys quantity shares of every symbol on the first bar it sees that
symbol, then never trades again. Standard performance baseline.

Ported from strategy.strategies.buy_and_hold.strategy.BuyAndHoldStrategy.
"""

from collections.abc import Awaitable, Callable
from typing import Any

from lib.math.actions import EnterLongAction
from lib.math.broker import BacktestBroker
from lib.math.portfolio import Portfolio
from lib.mechanics.models import Bar


class BuyAndHoldStrategy:
    """No explicit "already bought" flag needed: EnterLongAction already
    no-ops once a symbol has an open position, so calling it on every
    bar is naturally idempotent.
    """

    def __init__(self, quantity: int) -> None:
        self._enter_action = EnterLongAction(quantity=quantity)

    async def on_bar(self, bars: dict[str, Bar], portfolio: Portfolio, broker: BacktestBroker) -> None:
        for symbol, bar in bars.items():
            await self._enter_action.execute(symbol, bar, portfolio, broker)


OnBar = Callable[[dict[str, Bar], Portfolio, BacktestBroker], Awaitable[None]]


def make_buy_and_hold_on_bar(params: dict[str, Any]) -> OnBar:
    strategy = BuyAndHoldStrategy(**params)
    return strategy.on_bar
