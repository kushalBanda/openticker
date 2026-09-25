from datetime import UTC, datetime

import pytest

from openticker.adapters.sandbox.broker import SandboxBroker
from openticker.core.orders.models import OrderRequest, OrderStatus, OrderType
from openticker.ports.models import Product, Quote, Side
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from tests.fixtures.fake_broker import FAKE_INSTRUMENT
from tests.fixtures.priced_broker import PricedBroker
from tests.fixtures.sandbox import FRICTIONLESS

NOW = datetime(2026, 9, 22, 5, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _master() -> None:
    upsert_instruments([FAKE_INSTRUMENT])


def _holding(quantity: int, side: Side = Side.BUY) -> tuple[SandboxBroker, PricedBroker]:
    market = PricedBroker(1000.0)
    sandbox = SandboxBroker("fake", market, FRICTIONLESS, lambda: NOW)
    sandbox.place_order(
        OrderRequest(FAKE_INSTRUMENT, side, quantity, Product.MIS, OrderType.MARKET, None, "mcp")
    )
    return sandbox, market


def test_closes_exactly_what_is_held_and_releases_its_margin() -> None:
    sandbox, _ = _holding(10)

    result = sandbox.close_position(
        FAKE_INSTRUMENT, Product.MIS, Quote(FAKE_INSTRUMENT, 1010.0, NOW), NOW, "rest:bot"
    )

    assert (result.status, result.fill_price) == (OrderStatus.FILLED, 1010.0)
    assert result.broker_order_id is not None
    order = sandbox.get_order(result.broker_order_id)
    assert order is not None
    assert (order.side, order.quantity, order.triggered_by) == (Side.SELL, 10, "rest:bot")
    assert sandbox.open_positions() == []
    funds = sandbox.get_funds()
    assert (funds.used_margin, funds.realized_pnl) == (0.0, 100.0)


def test_a_short_is_closed_by_buying() -> None:
    sandbox, _ = _holding(4, Side.SELL)

    result = sandbox.close_position(
        FAKE_INSTRUMENT, Product.MIS, Quote(FAKE_INSTRUMENT, 990.0, NOW), NOW, "mcp"
    )

    assert result.broker_order_id is not None
    order = sandbox.get_order(result.broker_order_id)
    assert order is not None and (order.side, order.quantity) == (Side.BUY, 4)
    assert sandbox.get_funds().realized_pnl == 40.0


def test_the_quantity_is_read_when_the_fill_is_written() -> None:
    sandbox, _ = _holding(10)
    seen = sandbox.open_positions()[0].quantity
    sandbox.place_order(  # fills after the caller looked
        OrderRequest(FAKE_INSTRUMENT, Side.BUY, 5, Product.MIS, OrderType.MARKET, None, "mcp")
    )

    result = sandbox.close_position(
        FAKE_INSTRUMENT, Product.MIS, Quote(FAKE_INSTRUMENT, 1000.0, NOW), NOW, "mcp"
    )

    assert seen == 10
    assert result.broker_order_id is not None
    order = sandbox.get_order(result.broker_order_id)
    assert order is not None and order.quantity == 15
    assert sandbox.open_positions() == []


def test_nothing_held_is_refused_and_nothing_recorded() -> None:
    sandbox, _ = _holding(10)

    result = sandbox.close_position(
        FAKE_INSTRUMENT, Product.CNC, Quote(FAKE_INSTRUMENT, 1000.0, NOW), NOW, "mcp"
    )

    assert result.status is OrderStatus.REJECTED
    assert result.reason == "no open CNC position in RELIANCE"
    assert len(sandbox.get_orderbook(10)) == 1
