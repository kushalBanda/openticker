from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from openticker.adapters.sandbox.broker import SandboxBroker, SandboxSettings
from openticker.core.orders.models import OrderRequest, OrderStatus, OrderType
from openticker.events.types import OrderCancelled, OrderFailed, OrderFilled, OrderPlaced
from openticker.ports.models import Exchange, Instrument, InstrumentType, Product, Side
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from openticker.use_cases.cancel_all_orders import cancel_all_orders
from openticker.use_cases.close_all_positions import close_all_positions
from openticker.use_cases.close_position import NoOpenPositionError, close_position
from tests.fixtures.calendar import NO_HOLIDAYS
from tests.fixtures.fake_broker import FAKE_INSTRUMENT
from tests.fixtures.priced_broker import PricedBroker

OPEN = datetime(2026, 9, 22, 5, 0, tzinfo=UTC)  # Tuesday 10:30 IST
EVENING = datetime(2026, 9, 22, 11, 0, tzinfo=UTC)  # 16:30 IST: NSE closed, MCX open
CRUDE = replace(
    FAKE_INSTRUMENT,
    symbol="CRUDEOILM19OCT26FUT",
    broker_symbol="CRUDEOILM19OCT26FUT",
    exchange=Exchange.MCX,
    broker_exchange="MCX",
    token="fake-crude",
    expiry=date(2026, 10, 19),
    instrument_type=InstrumentType.FUT,
    tick_size=1.0,
)


class _Recorder:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


@pytest.fixture(autouse=True)
def _master() -> None:
    upsert_instruments([FAKE_INSTRUMENT, CRUDE])


def _sandbox(market: PricedBroker | None = None) -> SandboxBroker:
    return SandboxBroker("fake", market or PricedBroker(1000.0), SandboxSettings(), lambda: OPEN)


def _fill(sandbox: SandboxBroker, request: OrderRequest) -> None:
    assert sandbox.place_order(request).status in (OrderStatus.FILLED, OrderStatus.PENDING)


def _market(
    instrument: Instrument = FAKE_INSTRUMENT,
    side: Side = Side.BUY,
    qty: int = 10,
    product: Product = Product.MIS,
) -> OrderRequest:
    return OrderRequest(instrument, side, qty, product, OrderType.MARKET, None, "mcp")


def test_close_one_fills_and_publishes_placed_and_filled() -> None:
    sandbox = _sandbox()
    _fill(sandbox, _market(side=Side.SELL, qty=3))
    events = _Recorder()

    position, result = close_position(
        sandbox, FAKE_INSTRUMENT, Product.MIS, events, NO_HOLIDAYS, OPEN, "rest:bot"
    )

    assert (position.quantity, result.status) == (-3, OrderStatus.FILLED)
    placed, filled = events.events
    assert isinstance(placed, OrderPlaced) and isinstance(filled, OrderFilled)
    assert (filled.side, filled.quantity, filled.triggered_by) == ("BUY", 3, "rest:bot")
    assert sandbox.open_positions() == []


def test_close_one_with_nothing_held_says_where_to_look() -> None:
    with pytest.raises(NoOpenPositionError, match="get_positions"):
        close_position(
            _sandbox(), FAKE_INSTRUMENT, Product.MIS, _Recorder(), NO_HOLIDAYS, OPEN, "mcp"
        )


def test_close_one_without_a_fresh_price_is_refused_and_kept() -> None:
    market = PricedBroker(1000.0)
    sandbox = _sandbox(market)
    _fill(sandbox, _market())
    market.day_range = (1100.0, 1200.0)  # last price outside its own day: stale
    events = _Recorder()

    _, result = close_position(
        sandbox, FAKE_INSTRUMENT, Product.MIS, events, NO_HOLIDAYS, OPEN, "mcp"
    )

    assert result.status is OrderStatus.REJECTED
    assert result.reason == "no fresh price for RELIANCE (last 1000.0); not closed"
    assert [type(e) for e in events.events] == [OrderFailed]
    assert sandbox.open_positions()[0].quantity == 10


def test_an_expired_contract_is_left_for_settlement() -> None:
    sandbox = _sandbox()
    _fill(sandbox, _market(CRUDE, qty=1, product=Product.NRML))
    after_expiry = datetime(2026, 10, 20, 5, 0, tzinfo=UTC)
    events = _Recorder()

    _, result = close_position(
        sandbox, CRUDE, Product.NRML, events, NO_HOLIDAYS, after_expiry, "mcp"
    )

    assert result.status is OrderStatus.REJECTED
    assert result.reason == "CRUDEOILM19OCT26FUT expired on 2026-10-19"
    assert sandbox.open_positions()[0].quantity == 1


def test_close_all_closes_what_it_can_and_says_why_not_for_the_rest() -> None:
    sandbox = _sandbox()
    _fill(sandbox, _market(product=Product.CNC))
    _fill(sandbox, _market(CRUDE, Side.SELL, 2, Product.NRML))

    closed = close_all_positions(sandbox, _Recorder(), NO_HOLIDAYS, EVENING, "mcp")

    outcomes = {p.instrument.symbol: (r.status, r.reason) for p, r in closed}
    assert outcomes["CRUDEOILM19OCT26FUT"] == (OrderStatus.FILLED, None)
    status, reason = outcomes["RELIANCE"]
    assert status is OrderStatus.REJECTED and "NSE is closed" in (reason or "")
    assert [p.instrument.symbol for p in sandbox.open_positions()] == ["RELIANCE"]


def test_close_all_with_nothing_open_does_nothing() -> None:
    assert close_all_positions(_sandbox(), _Recorder(), NO_HOLIDAYS, OPEN, "mcp") == []


def test_cancel_all_withdraws_every_pending_order_and_frees_its_margin() -> None:
    sandbox = _sandbox()
    for price in (900.0, 950.0):
        _fill(
            sandbox,
            OrderRequest(FAKE_INSTRUMENT, Side.BUY, 1, Product.CNC, OrderType.LIMIT, price, "mcp"),
        )
    _fill(sandbox, _market(qty=1, product=Product.CNC))
    held = sandbox.get_funds().used_margin
    events = _Recorder()

    outcomes = cancel_all_orders(sandbox, events, "rest:bot")

    assert [r.status for _, r in outcomes] == [OrderStatus.CANCELLED] * 2
    assert sandbox.pending_orders() == []
    assert sandbox.get_funds().used_margin == held - 1850.0
    assert {e.triggered_by for e in events.events if isinstance(e, OrderCancelled)} == {"rest:bot"}
    assert cancel_all_orders(sandbox, events, "mcp") == []
