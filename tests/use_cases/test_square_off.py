from datetime import UTC, datetime

import pytest

from openticker.adapters.sandbox.broker import SandboxBroker, SandboxSettings
from openticker.core.orders.models import OrderRequest, OrderStatus, OrderType
from openticker.events.types import OrderFilled
from openticker.ports.models import Product, Side
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from openticker.use_cases.square_off import square_off_intraday
from tests.fixtures.calendar import NO_HOLIDAYS
from tests.fixtures.fake_broker import FAKE_INSTRUMENT
from tests.fixtures.priced_broker import PricedBroker

BEFORE = datetime(2026, 9, 22, 9, 44, tzinfo=UTC)  # 15:14 IST
AT_SQUARE_OFF = datetime(2026, 9, 22, 9, 45, tzinfo=UTC)  # 15:15 IST
NEXT_MORNING = datetime(2026, 9, 23, 2, 30, tzinfo=UTC)  # 08:00 IST, before the open


class _Events:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


@pytest.fixture
def sandbox() -> SandboxBroker:
    upsert_instruments([FAKE_INSTRUMENT])
    sandbox = SandboxBroker(
        "fake", PricedBroker(100.0), SandboxSettings(starting_capital=100_000.0)
    )
    for side, product in ((Side.SELL, Product.MIS), (Side.BUY, Product.CNC)):
        sandbox.place_order(
            OrderRequest(FAKE_INSTRUMENT, side, 5, product, OrderType.MARKET, None, "mcp")
        )
    return sandbox


def test_mis_is_closed_at_the_square_off_and_delivery_is_kept(sandbox: SandboxBroker) -> None:
    events = _Events()

    assert square_off_intraday(sandbox, sandbox, events, NO_HOLIDAYS, BEFORE) == []
    [result] = square_off_intraday(sandbox, sandbox, events, NO_HOLIDAYS, AT_SQUARE_OFF)

    assert result.status is OrderStatus.FILLED
    held = {(p.product, p.quantity) for p in sandbox.get_positions()}
    assert held == {(Product.MIS, 0), (Product.CNC, 5)}
    [filled] = [e for e in events.events if isinstance(e, OrderFilled)]
    assert (filled.side, filled.triggered_by) == ("BUY", "square-off")


def test_an_mis_position_the_daemon_missed_is_closed_before_the_next_open(
    sandbox: SandboxBroker,
) -> None:
    [result] = square_off_intraday(sandbox, sandbox, _Events(), NO_HOLIDAYS, NEXT_MORNING)

    assert result.status is OrderStatus.FILLED
    assert [p for p in sandbox.open_positions() if p.product is Product.MIS] == []


def test_an_expired_contract_is_left_for_settlement_not_retried() -> None:
    from dataclasses import replace
    from datetime import date

    option = replace(
        FAKE_INSTRUMENT, symbol="NIFTY22SEP2623400CE", token="1", expiry=date(2026, 9, 22)
    )
    upsert_instruments([option])
    sandbox = SandboxBroker(
        "fake", PricedBroker(100.0), SandboxSettings(starting_capital=100_000.0)
    )
    sandbox.place_order(
        OrderRequest(option, Side.BUY, 1, Product.MIS, OrderType.MARKET, None, "mcp")
    )
    events = _Events()

    assert square_off_intraday(sandbox, sandbox, events, NO_HOLIDAYS, NEXT_MORNING) == []
    assert events.events == []
