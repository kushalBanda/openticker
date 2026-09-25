from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from openticker.adapters.sandbox.broker import SandboxBroker
from openticker.core.orders.models import OrderRequest, OrderStatus, OrderType
from openticker.ports.models import Exchange, Instrument, InstrumentType, Product, Side
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from openticker.use_cases.settle_expired import settle_expired_positions
from tests.fixtures.calendar import NO_HOLIDAYS
from tests.fixtures.fake_broker import FAKE_INSTRUMENT
from tests.fixtures.options import NIFTY_INDEX, option
from tests.fixtures.priced_broker import PricedBroker
from tests.fixtures.sandbox import frictionless

EXPIRY = date(2026, 9, 22)
TRADING = datetime(2026, 9, 22, 5, 0, tzinfo=UTC)  # 10:30 IST on expiry day
BEFORE_FINAL = datetime(2026, 9, 22, 10, 14, tzinfo=UTC)  # 15:44 IST
AFTER_FINAL = datetime(2026, 9, 22, 10, 15, tzinfo=UTC)  # 15:45 IST
DAYS_LATER = datetime(2026, 9, 25, 4, 0, tzinfo=UTC)
CALL = option("NIFTY", EXPIRY, 23400, InstrumentType.CE)
PUT = option("NIFTY", EXPIRY, 23400, InstrumentType.PE)
FUTURE = replace(
    CALL, symbol="NIFTY22SEP26FUT", instrument_type=InstrumentType.FUT, strike=None, token="3"
)
GOLD = Instrument(
    "GOLD22SEP26FUT", "GOLD26SEPFUT", Exchange.MCX, "MCX", "4", EXPIRY, None, 1,
    InstrumentType.FUT, 1.0,
)  # fmt: skip


class _Events:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


@pytest.fixture
def market() -> PricedBroker:
    upsert_instruments([NIFTY_INDEX, CALL, PUT, FUTURE, GOLD, FAKE_INSTRUMENT])
    return PricedBroker(100.0)


def _sandbox(market: PricedBroker) -> SandboxBroker:
    return SandboxBroker("fake", market, frictionless(10_000_000.0))


def _hold(
    sandbox: SandboxBroker,
    market: PricedBroker,
    contract: Instrument,
    side: Side,
    price: float,
    product: Product = Product.NRML,
) -> None:
    market.price = price
    result = sandbox.place_order(
        OrderRequest(contract, side, contract.lot_size, product, OrderType.MARKET, None, "mcp")
    )
    assert result.status is OrderStatus.FILLED


def test_options_settle_at_intrinsic_value_from_the_index_close(market: PricedBroker) -> None:
    sandbox = _sandbox(market)
    _hold(sandbox, market, CALL, Side.BUY, 40.0)  # long call, in the money at expiry
    _hold(sandbox, market, PUT, Side.SELL, 30.0)  # short put, expires worthless
    market.closes[("NIFTY 50", EXPIRY)] = 23450.5
    events = _Events()

    run = settle_expired_positions(sandbox, sandbox, events, NO_HOLIDAYS, AFTER_FINAL)

    by_symbol = {e.symbol: e for e in run.settled}
    assert (by_symbol[CALL.symbol].price, by_symbol[CALL.symbol].realized_pnl) == (50.5, 65 * 10.5)
    assert (by_symbol[PUT.symbol].price, by_symbol[PUT.symbol].realized_pnl) == (0.0, 65 * 30.0)
    assert "NIFTY 50 closed at 23,450.50 on 2026-09-22" in by_symbol[CALL.symbol].detail
    assert sandbox.open_positions() == []
    funds = sandbox.get_funds()
    assert funds.used_margin == 0.0
    assert round(funds.realized_pnl, 2) == round(65 * 10.5 + 65 * 30.0, 2)
    settlements = [o for o in sandbox.get_orderbook(10) if o.triggered_by == "expiry-settlement"]
    assert len(settlements) == 2 and all(o.status is OrderStatus.FILLED for o in settlements)


def test_nothing_settles_until_the_close_is_final(market: PricedBroker) -> None:
    sandbox = _sandbox(market)
    _hold(sandbox, market, FUTURE, Side.BUY, 23400.0)
    market.closes[("NIFTY 50", EXPIRY)] = 23411.2

    early = settle_expired_positions(sandbox, sandbox, _Events(), NO_HOLIDAYS, BEFORE_FINAL)
    on_time = settle_expired_positions(sandbox, sandbox, _Events(), NO_HOLIDAYS, AFTER_FINAL)

    assert early.settled == [] and early.waiting == []
    assert [(e.price, e.realized_pnl) for e in on_time.settled] == [(23411.2, 65 * 11.2)]


def test_a_daemon_that_was_down_settles_days_later_from_the_expiry_day_close(
    market: PricedBroker,
) -> None:
    sandbox = _sandbox(market)
    _hold(sandbox, market, CALL, Side.SELL, 25.0, Product.MIS)  # an MIS the square-off missed
    market.closes[("NIFTY 50", EXPIRY)] = 23380.0
    market.closes[("NIFTY 50", date(2026, 9, 24))] = 24000.0  # later days don't matter

    [event] = settle_expired_positions(sandbox, sandbox, _Events(), NO_HOLIDAYS, DAYS_LATER).settled

    assert (event.price, event.product, event.quantity) == (0.0, "MIS", -65)


def test_a_contract_without_an_underlying_settles_at_its_own_close(market: PricedBroker) -> None:
    sandbox = _sandbox(market)
    _hold(sandbox, market, GOLD, Side.BUY, 110_000.0)
    market.closes[(GOLD.symbol, EXPIRY)] = 110_500.0

    [event] = settle_expired_positions(
        sandbox, sandbox, _Events(), NO_HOLIDAYS, datetime(2026, 9, 23, 4, 0, tzinfo=UTC)
    ).settled

    assert (event.price, event.realized_pnl) == (110_500.0, 500.0)


def test_a_missing_close_waits_and_says_why(market: PricedBroker) -> None:
    sandbox = _sandbox(market)
    _hold(sandbox, market, CALL, Side.BUY, 40.0)
    events = _Events()

    run = settle_expired_positions(sandbox, sandbox, events, NO_HOLIDAYS, AFTER_FINAL)
    market.down = True
    down = settle_expired_positions(sandbox, sandbox, events, NO_HOLIDAYS, AFTER_FINAL)

    assert run.settled == [] and run.waiting == [
        f"{CALL.symbol}: no 2026-09-22 close for NIFTY 50 yet"
    ]
    assert down.waiting == [f"{CALL.symbol}: broker unreachable"]
    assert events.events == [] and len(sandbox.open_positions()) == 1


def test_equity_and_unexpired_contracts_are_left_alone(market: PricedBroker) -> None:
    sandbox = _sandbox(market)
    _hold(sandbox, market, FAKE_INSTRUMENT, Side.BUY, 100.0, Product.CNC)
    later = replace(CALL, symbol="NIFTY29SEP2623400CE", expiry=date(2026, 9, 29), token="9")
    upsert_instruments([later])
    _hold(sandbox, market, later, Side.BUY, 40.0)

    run = settle_expired_positions(sandbox, sandbox, _Events(), NO_HOLIDAYS, DAYS_LATER)

    assert run.settled == [] and len(sandbox.open_positions()) == 2
