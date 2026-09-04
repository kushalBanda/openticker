from ingest.core.models import Bar

from strategy.core.action import EnterLongAction
from strategy.core.interfaces import Broker
from strategy.core.portfolio import Portfolio
from strategy.core.registry import register_strategy


@register_strategy("buy_and_hold")
class BuyAndHoldStrategy:
    """Buys `quantity` shares of every symbol on the first bar it sees
    that symbol, then never trades again. Standard performance baseline
    (see event-driven-backtester references e.g. mnubo/QuantStart-style
    BuyAndHoldStrategy) to compare an active strategy's return against
    no signal, no exit, no re-entry.

    No explicit "already bought" flag is needed: `EnterLongAction`
    already no-ops once a symbol has an open position, so calling it on
    every bar is naturally idempotent.
    """

    def __init__(self, quantity: int) -> None:
        self._enter_action = EnterLongAction(quantity=quantity)

    async def on_bar(self, bars: dict[str, Bar], portfolio: Portfolio, broker: Broker) -> None:
        for symbol, bar in bars.items():
            await self._enter_action.execute(symbol, bar, portfolio, broker)
