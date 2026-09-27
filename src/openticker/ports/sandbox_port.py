"""SandboxPort: what the daemon's execution engine needs from the sandbox
beyond BrokerPort, to fill resting orders and square off intraday positions
(ADR 11 in docs/adr)."""

from datetime import datetime
from typing import Protocol

from openticker.core.orders.models import Order, OrderResult
from openticker.core.orders.sandbox import PaperMargin
from openticker.ports.broker_port import BrokerPort
from openticker.ports.models import Instrument, Position, Product, Quote, Side


class SandboxPort(Protocol):
    def pending_orders(self) -> list[Order]:
        """Oldest first."""
        ...

    def fill_pending(self, order: Order, price: float, now: datetime) -> OrderResult:
        """Fills a pending order at `price`, or rejects it if the funds are no
        longer there. `order` is what `price` was matched against: one no
        longer pending, or changed since (modify_order), is left as it is,
        and the next price decides."""
        ...

    def arm_pending(self, order: Order, now: datetime) -> None:
        """Records that an SL order's trigger has been crossed, unless the
        order changed since `order` was read."""
        ...

    def expire_order(self, order_id: str, reason: str, now: datetime) -> OrderResult: ...

    def orders_of_run(self, run_id: str) -> list[Order]:
        """Every order a strategy run placed, oldest first: what it holds
        even when the run never recorded the fill."""
        ...

    def open_positions(self) -> list[Position]:
        """Every non-zero position, without prices: cheap enough to check often."""
        ...

    def close_position(
        self,
        instrument: Instrument,
        product: Product,
        quote: Quote,
        now: datetime,
        triggered_by: str,
    ) -> OrderResult:
        """A MARKET order against `quote`'s book for exactly the quantity
        held, read under the write lock, with its charges. Nothing held:
        REJECTED, nothing recorded. Whether the exchange is open and `quote`
        fresh is the caller's to check."""
        ...

    def settle_position(
        self, instrument: Instrument, product: Product, price: float, reason: str, now: datetime
    ) -> OrderResult:
        """Closes a position in an expired contract at `price`, bypassing the
        checks a tradeable order goes through."""
        ...

    def preview_margin(
        self, instrument: Instrument, side: Side, quantity: int, product: Product, price: float
    ) -> PaperMargin:
        """What filling this order at `price` would block and free, against
        the position held. Reads only."""
        ...


class OrderSandbox(BrokerPort, SandboxPort, Protocol):
    """The sandbox as the daemon uses it: orders and prices, plus the above."""
