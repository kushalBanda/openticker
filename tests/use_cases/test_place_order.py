from dataclasses import replace
from datetime import UTC, datetime

import pytest

from openticker.adapters.sandbox.broker import SandboxBroker, SandboxSettings
from openticker.core.orders.models import OrderRequest, OrderResult, OrderStatus, OrderType
from openticker.events.types import OrderFailed, OrderFilled, OrderPlaced, RiskBreached
from openticker.ports.models import Product, Side
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from openticker.use_cases.place_order import place_order
from tests.fixtures.calendar import NO_HOLIDAYS
from tests.fixtures.fake_broker import FAKE_INSTRUMENT
from tests.fixtures.priced_broker import PricedBroker

NOW = datetime(2026, 9, 22, 5, 0, tzinfo=UTC)


class _Recorder:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


class _CountingSandbox(SandboxBroker):
    def __init__(self, market: PricedBroker) -> None:
        super().__init__("fake", market, SandboxSettings(starting_capital=1_000_000.0))
        self.orders_placed = 0

    def place_order(self, request: OrderRequest) -> OrderResult:
        self.orders_placed += 1
        return super().place_order(request)


@pytest.fixture(autouse=True)
def _master() -> None:
    upsert_instruments([FAKE_INSTRUMENT])


def _order(side: Side = Side.BUY, quantity: int = 10, **changes: object) -> OrderRequest:
    request = OrderRequest(
        FAKE_INSTRUMENT, side, quantity, Product.MIS, OrderType.MARKET, None, "test"
    )
    return replace(request, **changes)  # type: ignore[arg-type]


def test_fill_publishes_placed_then_filled_and_nothing_else() -> None:
    events = _Recorder()

    result = place_order(
        _order(), _CountingSandbox(PricedBroker(100.0)), events, None, NO_HOLIDAYS, NOW
    )

    assert result.status is OrderStatus.FILLED
    assert [type(event) for event in events.events] == [OrderPlaced, OrderFilled]
    filled = events.events[1]
    assert isinstance(filled, OrderFilled) and filled.price == 100.0


def test_invalid_order_never_reaches_the_sandbox() -> None:
    sandbox, events = _CountingSandbox(PricedBroker()), _Recorder()

    result = place_order(_order(quantity=0), sandbox, events, None, NO_HOLIDAYS, NOW)

    assert result.status is OrderStatus.REJECTED
    assert sandbox.orders_placed == 0
    assert [type(event) for event in events.events] == [OrderFailed]


def test_capital_cap_breach_makes_no_order() -> None:
    sandbox, events = _CountingSandbox(PricedBroker(100.0)), _Recorder()

    result = place_order(_order(quantity=11), sandbox, events, 1_000.0, NO_HOLIDAYS, NOW)

    assert result.status is OrderStatus.REJECTED
    assert sandbox.orders_placed == 0
    [breach] = events.events
    assert isinstance(breach, RiskBreached) and breach.reason == "capital_cap"


def test_capital_cap_never_blocks_reducing_a_position() -> None:
    market = PricedBroker(100.0)
    sandbox, events = _CountingSandbox(market), _Recorder()
    place_order(_order(quantity=10), sandbox, events, 1_000.0, NO_HOLIDAYS, NOW)

    market.price = 500.0  # the position is now worth 5x the cap
    result = place_order(_order(Side.SELL, 4), sandbox, events, 1_000.0, NO_HOLIDAYS, NOW)

    assert result.status is OrderStatus.FILLED


def test_capital_cap_applies_to_a_fill_that_flips_the_position() -> None:
    sandbox, events = _CountingSandbox(PricedBroker(100.0)), _Recorder()
    place_order(_order(quantity=10), sandbox, events, None, NO_HOLIDAYS, NOW)

    # Long 10 to short 5: smaller than before, but a new short worth 500.
    result = place_order(_order(Side.SELL, 15), sandbox, events, 400.0, NO_HOLIDAYS, NOW)

    assert result.status is OrderStatus.REJECTED


def test_rejection_inside_the_sandbox_publishes_order_failed() -> None:
    events = _Recorder()

    result = place_order(
        _order(quantity=100_000),
        _CountingSandbox(PricedBroker(100.0)),
        events,
        None,
        NO_HOLIDAYS,
        NOW,
    )

    assert result.status is OrderStatus.REJECTED
    assert [type(event) for event in events.events] == [OrderFailed]


def test_broker_error_becomes_a_failed_order() -> None:
    market = PricedBroker()
    market.down = True
    events = _Recorder()

    result = place_order(_order(), _CountingSandbox(market), events, None, NO_HOLIDAYS, NOW)

    assert (result.status, result.reason) == (OrderStatus.FAILED, "broker unreachable")
    assert [type(event) for event in events.events] == [OrderFailed]


def test_market_order_is_refused_while_the_exchange_is_closed() -> None:
    sandbox = _CountingSandbox(PricedBroker(100.0))
    events = _Recorder()
    saturday = datetime(2026, 9, 26, 5, 0, tzinfo=UTC)
    after_close = datetime(2026, 9, 22, 10, 30, tzinfo=UTC)  # 16:00 IST

    weekend = place_order(_order(), sandbox, events, None, NO_HOLIDAYS, saturday)
    evening = place_order(_order(), sandbox, events, None, NO_HOLIDAYS, after_close)

    assert weekend.status is OrderStatus.REJECTED and evening.status is OrderStatus.REJECTED
    assert weekend.reason == "NSE is closed (weekend); it next opens Mon 28 Sep 09:15 IST"
    assert evening.reason == "NSE is closed (after the session); it next opens Wed 23 Sep 09:15 IST"
    assert sandbox.orders_placed == 0
    assert [type(event) for event in events.events] == [OrderFailed, OrderFailed]
