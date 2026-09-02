from typing import TYPE_CHECKING, Protocol

from data_engine.core.models import Bar

from strategy_engine.core.models import Fill, Order

if TYPE_CHECKING:
    from strategy_engine.core.portfolio import Portfolio


class Broker(Protocol):
    def submit_order(self, order: Order) -> None: ...

    def match_pending_orders(self, next_bar: Bar) -> list[Fill]: ...


class Strategy(Protocol):
    def on_bar(self, bar: Bar, portfolio: "Portfolio", broker: Broker) -> None: ...
