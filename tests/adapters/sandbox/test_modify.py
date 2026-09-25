from datetime import UTC, datetime, timedelta

import pytest

from openticker.adapters.sandbox.broker import SandboxBroker
from openticker.core.orders.models import (
    Order,
    OrderChanges,
    OrderRequest,
    OrderStatus,
    OrderType,
)
from openticker.ports.models import Product, Side, Tick
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


@pytest.fixture(autouse=True)
def _master() -> None:
    upsert_instruments([FAKE_INSTRUMENT])


def _sandbox(capital: float = 100_000.0) -> SandboxBroker:
    return SandboxBroker("fake", PricedBroker(1000.0), frictionless(capital), lambda: PLACED)


def _rest(
    sandbox: SandboxBroker,
    kind: OrderType = OrderType.LIMIT,
    price: float | None = 950.0,
    trigger: float | None = None,
    side: Side = Side.BUY,
) -> str:
    result = sandbox.place_order(
        OrderRequest(
            FAKE_INSTRUMENT, side, 10, Product.CNC, kind, price, "mcp", trigger_price=trigger
        )
    )
    assert result.status is OrderStatus.PENDING and result.broker_order_id
    return result.broker_order_id


def _order(sandbox: SandboxBroker, order_id: str) -> Order:
    order = sandbox.get_order(order_id)
    assert order is not None
    return order


def test_a_new_price_moves_the_margin_the_order_holds() -> None:
    sandbox = _sandbox()
    order_id = _rest(sandbox)
    assert sandbox.get_funds().used_margin == 9_500.0

    result = sandbox.modify_order(order_id, OrderChanges(price=900.0, quantity=20))

    assert result.status is OrderStatus.PENDING
    assert sandbox.get_funds().used_margin == 18_000.0
    order = _order(sandbox, order_id)
    assert (order.price, order.quantity, order.status) == (900.0, 20, OrderStatus.PENDING)


def test_a_change_the_funds_cannot_cover_is_refused_and_the_order_is_untouched() -> None:
    sandbox = _sandbox(capital=20_000.0)
    order_id = _rest(sandbox)

    result = sandbox.modify_order(order_id, OrderChanges(quantity=30))

    assert result.status is OrderStatus.REJECTED
    assert result.reason is not None and "insufficient sandbox funds" in result.reason
    assert sandbox.get_funds().used_margin == 9_500.0
    order = _order(sandbox, order_id)
    assert (order.quantity, order.status) == (10, OrderStatus.PENDING)


def test_a_change_through_the_market_fills_on_the_next_price_not_at_once() -> None:
    sandbox, events = _sandbox(), _Events()
    order_id = _rest(sandbox)

    result = sandbox.modify_order(order_id, OrderChanges(price=1005.0))  # market at 1000

    assert result.status is OrderStatus.PENDING
    assert sandbox.get_trades(PLACED, 10) == []
    tick = Tick(FAKE_INSTRUMENT, 1001.0, LATER)
    execute_resting_orders(sandbox, lambda _: tick, events, NO_HOLIDAYS, LATER)
    filled = _order(sandbox, order_id)
    assert (filled.status, filled.fill_price) == (OrderStatus.FILLED, 1005.0)  # at its limit


def test_an_order_that_already_filled_cannot_change() -> None:
    sandbox = _sandbox()
    order_id = _rest(sandbox)
    sandbox.fill_pending(_order(sandbox, order_id), 948.0, LATER)

    result = sandbox.modify_order(order_id, OrderChanges(price=900.0))

    assert result.status is OrderStatus.FILLED
    assert result.reason is not None and result.reason.endswith("nothing to change")
    assert _order(sandbox, order_id).price == 950.0


def test_a_fill_matched_before_a_change_does_not_land() -> None:
    """The daemon matched the old limit, then the change moved it away: the
    change wins and the next price decides."""
    sandbox = _sandbox()
    order_id = _rest(sandbox)
    matched = _order(sandbox, order_id)  # 948 crosses the 950 limit

    sandbox.modify_order(order_id, OrderChanges(price=900.0))
    late = sandbox.fill_pending(matched, 948.0, LATER)

    assert late.status is OrderStatus.PENDING
    assert sandbox.get_trades(PLACED, 10) == []
    assert sandbox.get_funds().used_margin == 9_000.0


def test_a_new_trigger_has_to_be_crossed_again() -> None:
    sandbox = _sandbox()
    order_id = _rest(sandbox, OrderType.SL, price=1020.0, trigger=1010.0)
    sandbox.arm_pending(_order(sandbox, order_id), LATER)

    sandbox.modify_order(order_id, OrderChanges(price=1030.0))
    assert _order(sandbox, order_id).triggered
    sandbox.modify_order(order_id, OrderChanges(trigger_price=1025.0))
    assert not _order(sandbox, order_id).triggered


def test_arming_matched_before_a_change_does_not_land() -> None:
    sandbox = _sandbox()
    order_id = _rest(sandbox, OrderType.SL, price=1020.0, trigger=1010.0)
    matched = _order(sandbox, order_id)

    sandbox.modify_order(order_id, OrderChanges(trigger_price=1015.0, price=1025.0))
    sandbox.arm_pending(matched, LATER)

    assert not _order(sandbox, order_id).triggered
