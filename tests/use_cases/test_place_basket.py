from datetime import UTC, datetime

import pytest

from openticker.adapters.sandbox.broker import SandboxBroker, SandboxSettings
from openticker.core.orders.models import OrderStatus, OrderType
from openticker.events.bus import EventBus
from openticker.ports.models import Exchange, Product, Side
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from openticker.use_cases.errors import BatchTooLargeError
from openticker.use_cases.place_basket import MAX_BASKET, BasketOrder, place_basket
from tests.fixtures.calendar import NO_HOLIDAYS
from tests.fixtures.fake_broker import FAKE_INSTRUMENT
from tests.fixtures.priced_broker import PricedBroker

OPEN = datetime(2026, 9, 22, 5, 0, tzinfo=UTC)  # Tuesday 10:30 IST


@pytest.fixture(autouse=True)
def _master() -> None:
    upsert_instruments([FAKE_INSTRUMENT])


def _sandbox() -> SandboxBroker:
    return SandboxBroker("fake", PricedBroker(1000.0), SandboxSettings(), lambda: OPEN)


def _order(side: Side, **fields: object) -> BasketOrder:
    defaults: dict[str, object] = {
        "symbol": "RELIANCE",
        "exchange": Exchange.NSE,
        "side": side,
        "quantity": 10,
        "product": Product.CNC,
    }
    return BasketOrder(**{**defaults, **fields})  # type: ignore[arg-type]


def _place(sandbox: SandboxBroker, orders: list[BasketOrder]) -> list[tuple[Side, OrderStatus]]:
    placed = place_basket(orders, sandbox, EventBus(), None, NO_HOLIDAYS, OPEN, "rest:bot")
    return [(p.order.side, p.result.status) for p in placed]


def test_buys_go_first_so_a_sell_can_close_what_the_basket_bought() -> None:
    sandbox = _sandbox()

    placed = _place(sandbox, [_order(Side.SELL), _order(Side.BUY)])

    # CNC can't be sold short: placed in the caller's order, the sell is refused.
    assert placed == [(Side.BUY, OrderStatus.FILLED), (Side.SELL, OrderStatus.FILLED)]
    assert sandbox.open_positions() == []
    assert {order.triggered_by for order in sandbox.get_orderbook(10)} == {"rest:bot"}


def test_a_refused_order_does_not_stop_the_rest() -> None:
    sandbox = _sandbox()

    placed = place_basket(
        [
            _order(Side.BUY, symbol="NOPE"),
            _order(Side.BUY, order_type=OrderType.LIMIT),  # no limit price
            _order(Side.BUY, quantity=1),
        ],
        sandbox,
        EventBus(),
        None,
        NO_HOLIDAYS,
        OPEN,
        "mcp",
    )

    assert [p.result.status for p in placed] == [
        OrderStatus.REJECTED,
        OrderStatus.REJECTED,
        OrderStatus.FILLED,
    ]
    assert "sync_instruments" in (placed[0].result.reason or "")
    assert placed[0].order.symbol == "NOPE"
    assert [(p.instrument.symbol, p.quantity) for p in sandbox.open_positions()] == [
        ("RELIANCE", 1)
    ]


def test_more_than_the_limit_is_refused_before_anything_is_placed() -> None:
    sandbox = _sandbox()

    with pytest.raises(BatchTooLargeError, match=str(MAX_BASKET)):
        _place(sandbox, [_order(Side.BUY, quantity=1)] * (MAX_BASKET + 1))

    assert sandbox.get_orderbook(10) == []
