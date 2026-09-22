from datetime import UTC, datetime
from itertools import pairwise

from openticker.adapters.inbound.daemon.execution_loop import (
    SQUARE_OFF_CHECK,
    SQUARE_OFF_RETRY,
    ExecutionLoop,
)
from openticker.adapters.inbound.daemon.prices import LatestPrices
from openticker.adapters.sandbox.broker import SandboxBroker, SandboxSettings
from openticker.core.orders.models import OrderRequest, OrderType
from openticker.events.types import OrderFailed
from openticker.ports.models import Product, Side
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from tests.fixtures.calendar import NO_HOLIDAYS
from tests.fixtures.fake_broker import FAKE_INSTRUMENT
from tests.fixtures.priced_broker import PricedBroker

OPEN = datetime(2026, 9, 22, 5, 0, tzinfo=UTC)
AFTER_SQUARE_OFF = datetime(2026, 9, 22, 9, 50, tzinfo=UTC)


class _Events:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


class _Clock:
    def __init__(self, now: datetime) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def test_a_failed_square_off_is_retried_after_a_pause_not_every_pass() -> None:
    upsert_instruments([FAKE_INSTRUMENT])
    market = PricedBroker(100.0)
    clock = _Clock(OPEN)
    sandbox = SandboxBroker("fake", market, SandboxSettings(), clock)
    sandbox.place_order(
        OrderRequest(FAKE_INSTRUMENT, Side.BUY, 5, Product.MIS, OrderType.MARKET, None, "mcp")
    )
    events = _Events()
    loop = ExecutionLoop(lambda: sandbox, LatestPrices(), events, lambda: NO_HOLIDAYS, clock)
    market.down = True
    clock.now = AFTER_SQUARE_OFF
    loop.step()
    clock.now += SQUARE_OFF_CHECK
    loop.step()  # too soon to retry
    assert len([p for p in sandbox.open_positions() if p.product is Product.MIS]) == 1
    assert len([e for e in events.events if isinstance(e, OrderFailed)]) == 1

    market.down = False
    clock.now = AFTER_SQUARE_OFF + SQUARE_OFF_RETRY
    loop.step()

    assert [p for p in sandbox.open_positions() if p.product is Product.MIS] == []


def test_repeated_square_off_failures_back_off_to_an_hour() -> None:
    upsert_instruments([FAKE_INSTRUMENT])
    market = PricedBroker(100.0)
    clock = _Clock(OPEN)
    sandbox = SandboxBroker("fake", market, SandboxSettings(), clock)
    sandbox.place_order(
        OrderRequest(FAKE_INSTRUMENT, Side.BUY, 5, Product.MIS, OrderType.MARKET, None, "mcp")
    )
    events = _Events()
    loop = ExecutionLoop(lambda: sandbox, LatestPrices(), events, lambda: NO_HOLIDAYS, clock)
    market.down = True
    attempts: list[datetime] = []

    clock.now = AFTER_SQUARE_OFF
    for _ in range(8 * 60 * 2):  # the evening, until 23:20, a pass every 30 seconds
        before = len(events.events)
        loop.step()
        if len(events.events) > before:
            attempts.append(clock.now)
        clock.now += SQUARE_OFF_CHECK

    gaps = [(b - a).total_seconds() / 60 for a, b in pairwise(attempts)]
    assert gaps[:5] == [5, 10, 20, 40, 60]
    assert max(gaps) == 60


def test_a_settlement_waiting_for_its_close_is_retried_with_backoff() -> None:
    from datetime import date

    from openticker.core.orders.sandbox import NetPosition
    from openticker.ports.models import Bar, Instrument, InstrumentType
    from openticker.storage.sqlite.sandbox_repo import fill_transaction, save_position
    from tests.fixtures.options import NIFTY_INDEX, option

    class _CountingMarket(PricedBroker):
        asked = 0

        def get_historical_bars(
            self, instrument: Instrument, interval: str, start: date, end: date
        ) -> list[Bar]:
            self.asked += 1
            return super().get_historical_bars(instrument, interval, start, end)

    expired = option("NIFTY", date(2026, 9, 15), 23400, InstrumentType.CE)
    upsert_instruments([NIFTY_INDEX, expired])
    with fill_transaction() as session:
        save_position(
            session, "NFO", expired.symbol, Product.NRML, NetPosition(65, 50.0, 3250.0, 0.0)
        )
    market = _CountingMarket(100.0)
    clock = _Clock(OPEN)
    sandbox = SandboxBroker("fake", market, SandboxSettings(), clock)
    loop = ExecutionLoop(lambda: sandbox, LatestPrices(), _Events(), lambda: NO_HOLIDAYS, clock)

    for _ in range(20):  # ten minutes of passes, 30 seconds apart
        loop.step()
        clock.now += SQUARE_OFF_CHECK

    assert market.asked == 2  # at once, then 5 minutes later
