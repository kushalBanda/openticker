"""A sandbox whose clock and prices a test moves, for the P&L by day and
minute (ADR 34 in docs/adr)."""

from dataclasses import replace
from datetime import UTC, date, datetime, time

from openticker.adapters.sandbox.broker import SandboxBroker
from openticker.core.orders.models import OrderRequest, OrderStatus, OrderType
from openticker.ports.models import EXCHANGE_TIMEZONE, Product, Side
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from tests.fixtures.fake_broker import FAKE_INSTRUMENT
from tests.fixtures.priced_broker import PricedBroker
from tests.fixtures.sandbox import FRICTIONLESS

MONDAY = date(2026, 9, 21)
TUESDAY = date(2026, 9, 22)


def at(day: date, hh: int, mm: int) -> datetime:
    return datetime.combine(day, time(hh, mm), EXCHANGE_TIMEZONE).astimezone(UTC)


class Desk:
    """A sandbox whose clock and prices the test moves."""

    def __init__(self) -> None:
        self.now = at(MONDAY, 10, 0)
        self.market = PricedBroker(1000.0)
        # Charges on, so "after charges" means something; no slippage.
        settings = replace(FRICTIONLESS, charges=None)
        self.sandbox = SandboxBroker("fake", self.market, settings, lambda: self.now)

    def trade(self, side: Side, qty: int, product: Product = Product.CNC) -> None:
        request = OrderRequest(FAKE_INSTRUMENT, side, qty, product, OrderType.MARKET, None, "ui")
        assert self.sandbox.place_order(request).status is OrderStatus.FILLED


def new_desk() -> Desk:
    upsert_instruments([FAKE_INSTRUMENT])
    return Desk()
