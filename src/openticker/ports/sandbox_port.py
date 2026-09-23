"""SandboxPort: what the daemon's execution engine needs from the sandbox
beyond BrokerPort, to fill resting orders and square off intraday positions
(ADR 11 in docs/adr)."""

from datetime import datetime
from typing import Protocol

from openticker.core.orders.models import Order, OrderResult
from openticker.ports.broker_port import BrokerPort
from openticker.ports.models import Instrument, Position, Product


class SandboxPort(Protocol):
    def pending_orders(self) -> list[Order]:
        """Oldest first."""
        ...

    def fill_pending(self, order_id: str, price: float, now: datetime) -> OrderResult:
        """Fills a pending order at `price`, or rejects it if the funds are no
        longer there. An order no longer pending is left as it is."""
        ...

    def arm_pending(self, order_id: str, now: datetime) -> None:
        """Records that an SL order's trigger has been crossed."""
        ...

    def expire_order(self, order_id: str, reason: str, now: datetime) -> OrderResult: ...

    def orders_of_run(self, run_id: str) -> list[Order]:
        """Every order a strategy run placed, oldest first: what it holds
        even when the run never recorded the fill."""
        ...

    def open_positions(self) -> list[Position]:
        """Every non-zero position, without prices: cheap enough to check often."""
        ...

    def settle_position(
        self, instrument: Instrument, product: Product, price: float, reason: str, now: datetime
    ) -> OrderResult:
        """Closes a position in an expired contract at `price`, bypassing the
        checks a tradeable order goes through."""
        ...


class OrderSandbox(BrokerPort, SandboxPort, Protocol):
    """The sandbox as the daemon uses it: orders and prices, plus the above."""
