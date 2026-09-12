from typing import Protocol

from ingest.core.models import Bar, Tick

from strategy.core.models import Fill, Order, OrderState
from strategy.core.portfolio import Portfolio


class Broker(Protocol):
    async def submit_order(self, order: Order) -> OrderState: ...

    async def cancel_order(self, order_id: str) -> None: ...

    async def get_fills(self, order_id: str) -> list[Fill]: ...

    # Bar-batch fill path, driven by BacktestEngine.run(). PaperBroker/
    # LiveBroker do not use this - they fill against on_tick instead - and
    # raise NotImplementedError, same as BacktestBroker does today for
    # cancel_order/get_fills.
    async def match_pending_orders(self, next_bars: dict[str, Bar]) -> list[Fill]: ...

    # Tick-driven fill path, for a live tick stream (see
    # ingest.core.engine.DataEngine.subscribe_live). BacktestBroker has no
    # tick stream to fill against and raises NotImplementedError.
    async def on_tick(self, tick: Tick) -> list[Fill]: ...

    # Called once after the last bar, returns orders left with no next bar to fill against.
    async def close(self) -> list[Order]: ...


class Strategy(Protocol):
    async def on_bar(
        self, bars: dict[str, Bar], portfolio: "Portfolio", broker: Broker
    ) -> None: ...
