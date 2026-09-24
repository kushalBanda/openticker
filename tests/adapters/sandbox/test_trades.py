from datetime import UTC, datetime, timedelta

import pytest

from openticker.adapters.sandbox.broker import SandboxBroker, SandboxSettings
from openticker.core.orders.models import OrderRequest, OrderType
from openticker.ports.models import Product, Side
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from tests.fixtures.fake_broker import FAKE_INSTRUMENT
from tests.fixtures.priced_broker import PricedBroker

MORNING = datetime(2026, 9, 22, 4, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _master() -> None:
    upsert_instruments([FAKE_INSTRUMENT])


class _Clock:
    def __init__(self) -> None:
        self.now = MORNING

    def __call__(self) -> datetime:
        return self.now


def _request(
    side: Side, kind: OrderType = OrderType.MARKET, price: float | None = None
) -> OrderRequest:
    return OrderRequest(FAKE_INSTRUMENT, side, 1, Product.MIS, kind, price, "mcp", "s1", "r1")


def test_trades_since_newest_first_with_who_placed_them() -> None:
    clock = _Clock()
    sandbox = SandboxBroker("fake", PricedBroker(price=100.0), SandboxSettings(), clock)
    first = sandbox.place_order(_request(Side.BUY))
    clock.now += timedelta(minutes=5)
    second = sandbox.place_order(_request(Side.SELL))

    trades = sandbox.get_trades(MORNING, 10)
    later = sandbox.get_trades(MORNING + timedelta(minutes=1), 10)

    assert [t.order_id for t in trades] == [second.broker_order_id, first.broker_order_id]
    assert [(t.side, t.price, t.triggered_by, t.strategy_id) for t in trades] == [
        (Side.SELL, 100.0, "mcp", "s1"),
        (Side.BUY, 100.0, "mcp", "s1"),
    ]
    assert [t.order_id for t in later] == [second.broker_order_id]
    assert len(sandbox.get_trades(MORNING, 1)) == 1


def test_a_resting_order_trades_when_it_fills_not_when_placed() -> None:
    clock = _Clock()
    sandbox = SandboxBroker("fake", PricedBroker(price=100.0), SandboxSettings(), clock)
    placed = sandbox.place_order(_request(Side.BUY, OrderType.LIMIT, 95.0))
    assert placed.broker_order_id is not None and sandbox.get_trades(MORNING, 10) == []

    filled_at = MORNING + timedelta(hours=1)
    sandbox.fill_pending(placed.broker_order_id, 95.0, filled_at)

    [trade] = sandbox.get_trades(MORNING, 10)
    assert (trade.order_id, trade.price, trade.filled_at) == (
        placed.broker_order_id,
        95.0,
        filled_at,
    )
