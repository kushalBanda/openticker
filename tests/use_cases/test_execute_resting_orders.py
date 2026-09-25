from datetime import UTC, datetime, timedelta

import pytest

from openticker.adapters.sandbox.broker import SandboxBroker
from openticker.core.orders.models import OrderRequest, OrderStatus, OrderType
from openticker.events.types import OrderCancelled, OrderFilled
from openticker.ports.models import Instrument, Product, Side, Tick
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from openticker.use_cases.execute_resting_orders import execute_resting_orders
from tests.fixtures.calendar import NO_HOLIDAYS
from tests.fixtures.fake_broker import FAKE_INSTRUMENT
from tests.fixtures.priced_broker import PricedBroker
from tests.fixtures.sandbox import frictionless

PLACED = datetime(2026, 9, 22, 5, 0, tzinfo=UTC)  # Tuesday 10:30 IST
LATER = PLACED + timedelta(minutes=5)


class _Events:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


class _Prices:
    def __init__(self) -> None:
        self.tick: Tick | None = None

    def set(self, price: float, at: datetime) -> None:
        self.tick = Tick(FAKE_INSTRUMENT, price, at)

    def __call__(self, instrument: Instrument) -> Tick | None:
        return self.tick


@pytest.fixture(autouse=True)
def _master() -> None:
    upsert_instruments([FAKE_INSTRUMENT])


def _sandbox() -> SandboxBroker:
    return SandboxBroker("fake", PricedBroker(1000.0), frictionless(100_000.0), lambda: PLACED)


def _place(
    sandbox: SandboxBroker,
    kind: OrderType,
    side: Side = Side.BUY,
    price: float | None = None,
    trigger: float | None = None,
    product: Product = Product.NRML,
) -> str:
    result = sandbox.place_order(
        OrderRequest(FAKE_INSTRUMENT, side, 10, product, kind, price, "mcp", trigger_price=trigger)
    )
    assert result.status is OrderStatus.PENDING and result.broker_order_id
    return result.broker_order_id


def test_a_live_price_crossing_the_limit_fills_it_and_notifies() -> None:
    sandbox, prices, events = _sandbox(), _Prices(), _Events()
    order_id = _place(sandbox, OrderType.LIMIT, price=950.0, product=Product.CNC)

    prices.set(951.0, LATER)
    execute_resting_orders(sandbox, prices, events, NO_HOLIDAYS, LATER)
    prices.set(949.5, LATER)
    execute_resting_orders(sandbox, prices, events, NO_HOLIDAYS, LATER)

    [order] = sandbox.get_orderbook(5)
    assert (order.order_id, order.status, order.fill_price) == (order_id, "FILLED", 950.0)
    [filled] = events.events
    assert isinstance(filled, OrderFilled) and filled.triggered_by == "mcp"


def test_a_price_seen_before_the_order_was_placed_never_fills_it() -> None:
    sandbox, prices, events = _sandbox(), _Prices(), _Events()
    _place(sandbox, OrderType.LIMIT, price=950.0, product=Product.CNC)
    prices.set(900.0, PLACED - timedelta(seconds=1))

    execute_resting_orders(sandbox, prices, events, NO_HOLIDAYS, LATER)

    assert len(sandbox.pending_orders()) == 1 and events.events == []


def test_an_sl_arms_on_its_trigger_and_fills_later_at_its_limit() -> None:
    sandbox, prices, events = _sandbox(), _Prices(), _Events()
    _place(sandbox, OrderType.SL, price=1030.0, trigger=1020.0)

    prices.set(1035.0, LATER)  # through the trigger, above the limit: armed, not filled
    execute_resting_orders(sandbox, prices, events, NO_HOLIDAYS, LATER)
    [armed] = sandbox.pending_orders()
    prices.set(1015.0, LATER + timedelta(seconds=1))  # back below the trigger: fills as a limit
    execute_resting_orders(sandbox, prices, events, NO_HOLIDAYS, LATER)

    assert armed.triggered
    [order] = sandbox.get_orderbook(1)
    assert (order.status, order.fill_price) == ("FILLED", 1030.0)  # at its limit


def test_day_orders_expire_at_the_close_and_mis_at_the_square_off() -> None:
    sandbox, prices, events = _sandbox(), _Prices(), _Events()
    nrml = _place(sandbox, OrderType.LIMIT, price=900.0)
    mis = _place(sandbox, OrderType.LIMIT, price=900.0, product=Product.MIS)
    square_off = datetime(2026, 9, 22, 9, 45, tzinfo=UTC)  # 15:15 IST
    close = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)  # 15:30 IST

    execute_resting_orders(sandbox, prices, events, NO_HOLIDAYS, square_off - timedelta(seconds=1))
    assert len(sandbox.pending_orders()) == 2
    execute_resting_orders(sandbox, prices, events, NO_HOLIDAYS, square_off)
    assert [o.order_id for o in sandbox.pending_orders()] == [nrml]
    execute_resting_orders(sandbox, prices, events, NO_HOLIDAYS, close)

    assert sandbox.pending_orders() == []
    assert sandbox.get_funds().used_margin == 0.0
    assert [(e.order_id, e.reason) for e in events.events if isinstance(e, OrderCancelled)] == [
        (mis, "expired at the intraday square-off"),
        (nrml, "expired at the session's close"),
    ]
