from typing import Protocol

from ingest.core.models import Bar

from strategy.core.models import Fill, Order, OrderState
from strategy.core.portfolio import Portfolio


class Broker(Protocol):
    async def submit_order(self, order: Order) -> OrderState: ...

    async def cancel_order(self, order_id: str) -> None: ...

    async def get_fills(self, order_id: str) -> list[Fill]: ...

    async def match_pending_orders(self, next_bar: Bar) -> list[Fill]: ...

    # Called once after the last bar, returns orders left with no next bar to fill against.
    async def close(self) -> list[Order]: ...


class Strategy(Protocol):
    async def on_bar(self, bar: Bar, portfolio: "Portfolio", broker: Broker) -> None: ...
