from datetime import UTC, datetime

import pytest

from openticker.adapters.sandbox.broker import SandboxBroker
from openticker.core.orders.models import OrderChanges, OrderRequest, OrderStatus, OrderType
from openticker.events.types import OrderModified, RiskBreached
from openticker.ports.models import Product, Side
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from openticker.use_cases.errors import UnknownOrderError
from openticker.use_cases.modify_order import modify_order
from tests.fixtures.calendar import NO_HOLIDAYS
from tests.fixtures.fake_broker import FAKE_INSTRUMENT
from tests.fixtures.priced_broker import PricedBroker
from tests.fixtures.sandbox import FRICTIONLESS

OPEN = datetime(2026, 9, 22, 5, 0, tzinfo=UTC)  # Tuesday 10:30 IST
CLOSED = datetime(2026, 9, 22, 11, 0, tzinfo=UTC)  # Tuesday 16:30 IST


class _Recorder:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


@pytest.fixture(autouse=True)
def _master() -> None:
    upsert_instruments([FAKE_INSTRUMENT])


def _resting(product: Product = Product.CNC) -> tuple[SandboxBroker, str]:
    sandbox = SandboxBroker("fake", PricedBroker(1000.0), FRICTIONLESS, lambda: OPEN)
    result = sandbox.place_order(
        OrderRequest(FAKE_INSTRUMENT, Side.BUY, 10, product, OrderType.LIMIT, 950.0, "mcp")
    )
    assert result.broker_order_id is not None
    return sandbox, result.broker_order_id


def test_a_change_publishes_what_changed_and_who_changed_it() -> None:
    sandbox, order_id = _resting()
    events = _Recorder()

    result = modify_order(
        order_id, OrderChanges(price=960.0), sandbox, events, None, NO_HOLIDAYS, OPEN, "rest:bot"
    )

    assert result.status is OrderStatus.PENDING
    [event] = events.events
    assert isinstance(event, OrderModified)
    assert (event.order_id, event.symbol, event.change, event.triggered_by) == (
        order_id,
        "RELIANCE",
        "price 950.0 -> 960.0",
        "rest:bot",
    )


@pytest.mark.parametrize(
    ("changes", "now", "reason"),
    [
        (OrderChanges(price=960.0), CLOSED, "NSE is closed"),
        (OrderChanges(price=960.03), OPEN, "not a multiple of the tick size 0.05"),
        (OrderChanges(trigger_price=960.0), OPEN, "LIMIT orders take no trigger_price"),
    ],
)
def test_a_refused_change_leaves_the_order_and_publishes_nothing(
    changes: OrderChanges, now: datetime, reason: str
) -> None:
    sandbox, order_id = _resting()
    events = _Recorder()

    result = modify_order(order_id, changes, sandbox, events, None, NO_HOLIDAYS, now, "mcp")

    assert result.status is OrderStatus.REJECTED
    assert result.reason is not None and reason in result.reason
    assert events.events == []
    order = sandbox.get_order(order_id)
    assert order is not None and order.price == 950.0


def test_an_unknown_order_names_the_way_to_find_one() -> None:
    sandbox, _ = _resting()

    with pytest.raises(UnknownOrderError, match="get_orderbook"):
        modify_order(
            "SBNOPE", OrderChanges(price=1.0), sandbox, _Recorder(), None, NO_HOLIDAYS, OPEN, "mcp"
        )


def test_growing_past_the_capital_cap_is_refused_but_a_price_change_is_not() -> None:
    sandbox, order_id = _resting()  # 10 at a market of 1000: worth 10,000
    events = _Recorder()

    grown = modify_order(
        order_id, OrderChanges(quantity=20), sandbox, events, 12_000.0, NO_HOLIDAYS, OPEN, "mcp"
    )
    repriced = modify_order(
        order_id, OrderChanges(price=960.0), sandbox, _Recorder(), 5_000.0, NO_HOLIDAYS, OPEN, "mcp"
    )

    assert grown.status is OrderStatus.REJECTED
    [breach] = events.events
    assert isinstance(breach, RiskBreached) and breach.reason == "capital_cap"
    assert repriced.status is OrderStatus.PENDING
    order = sandbox.get_order(order_id)
    assert order is not None and (order.quantity, order.price) == (10, 960.0)


def test_an_intraday_order_cannot_grow_after_the_square_off() -> None:
    sandbox, order_id = _resting(Product.MIS)
    at_1520 = datetime(2026, 9, 22, 9, 50, tzinfo=UTC)

    grown = modify_order(
        order_id, OrderChanges(quantity=20), sandbox, _Recorder(), None, NO_HOLIDAYS, at_1520, "mcp"
    )
    repriced = modify_order(
        order_id, OrderChanges(price=960.0), sandbox, _Recorder(), None, NO_HOLIDAYS, at_1520, "mcp"
    )

    assert grown.status is OrderStatus.REJECTED
    assert grown.reason is not None and "after the 15:15 square-off" in grown.reason
    assert repriced.status is OrderStatus.PENDING
