from collections.abc import Sequence
from datetime import date, datetime
from typing import Protocol

from openticker.core.orders.charge_check import ChargeSample
from openticker.core.orders.charges import Charges
from openticker.core.orders.models import (
    Order,
    OrderChanges,
    OrderRequest,
    OrderResult,
    Trade,
)
from openticker.ports.models import (
    Bar,
    Credentials,
    Funds,
    Instrument,
    MarginRequirement,
    MarketDepth,
    Position,
    Quote,
)


class BrokerPort(Protocol):
    def authenticate(self, request_token: str) -> Credentials: ...
    def get_instrument_master(self) -> list[Instrument]: ...
    def get_quote(self, instrument: Instrument) -> Quote: ...
    def get_quotes(self, instruments: Sequence[Instrument]) -> list[Quote]:
        """One quote per instrument that has one, in any order; an instrument
        the broker returns nothing for is left out rather than failing the batch."""
        ...

    def get_market_depth(self, instrument: Instrument) -> MarketDepth: ...
    def get_margin(self, orders: Sequence[OrderRequest]) -> MarginRequirement:
        """The broker's own figure; nothing is placed."""
        ...

    def get_charges(self, orders: Sequence[ChargeSample]) -> list[Charges]:
        """The broker's own charges for these orders as executed, in their
        order, from its contract note. Nothing is placed. The orders are taken
        as one day's trades: a buy and a sell of the same contract may be
        charged as an intraday round trip."""
        ...

    def get_historical_bars(
        self, instrument: Instrument, interval: str, start: date, end: date
    ) -> list[Bar]: ...
    # The order side: only the sandbox implements it (ADR 11 in docs/adr).
    def place_order(self, request: OrderRequest) -> OrderResult: ...
    def get_positions(self) -> list[Position]: ...
    def get_funds(self) -> Funds: ...
    def get_orderbook(self, limit: int) -> list[Order]:
        """Most recent first."""
        ...

    def get_order(self, order_id: str) -> Order | None: ...
    def cancel_order(self, order_id: str) -> OrderResult:
        """Withdraws a pending order. The result carries the order's status
        afterwards, with a reason when there was nothing to cancel."""
        ...

    def modify_order(self, order_id: str, changes: OrderChanges) -> OrderResult:
        """Changes a pending order's quantity, price or trigger; never fills
        it. A refused change leaves the order as it was, and the result says
        why."""
        ...

    def get_trades(self, since: datetime, limit: int) -> list[Trade]:
        """Fills at or after `since`, newest first."""
        ...
