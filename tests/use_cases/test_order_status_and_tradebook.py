from datetime import UTC, datetime

import pytest

from openticker.adapters.sandbox.broker import SandboxBroker
from openticker.core.orders.models import OrderRequest, OrderStatus, OrderType
from openticker.ports.models import Product, Side
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from openticker.use_cases.errors import UnknownOrderError
from openticker.use_cases.get_order_status import get_order_status
from openticker.use_cases.get_tradebook import get_tradebook
from tests.fixtures.fake_broker import FAKE_INSTRUMENT
from tests.fixtures.priced_broker import PricedBroker
from tests.fixtures.sandbox import FRICTIONLESS


@pytest.fixture(autouse=True)
def _master() -> None:
    upsert_instruments([FAKE_INSTRUMENT])


def _buy_at(moment: datetime) -> SandboxBroker:
    sandbox = SandboxBroker("fake", PricedBroker(), FRICTIONLESS, lambda: moment)
    sandbox.place_order(
        OrderRequest(FAKE_INSTRUMENT, Side.BUY, 1, Product.NRML, OrderType.MARKET, None, "mcp")
    )
    return sandbox


def test_today_is_the_exchange_local_date() -> None:
    # 23:00 IST Monday (an MCX evening fill) is 17:30 UTC Monday.
    sandbox = _buy_at(datetime(2026, 9, 21, 17, 30, tzinfo=UTC))
    monday_night = datetime(2026, 9, 21, 18, 0, tzinfo=UTC)  # 23:30 IST Monday
    tuesday_early = datetime(2026, 9, 21, 19, 0, tzinfo=UTC)  # 00:30 IST Tuesday, same UTC day

    assert len(get_tradebook(sandbox, 10, monday_night)) == 1
    assert get_tradebook(sandbox, 10, tuesday_early) == []


def test_order_status_returns_the_order_or_names_the_way_to_find_one() -> None:
    sandbox = _buy_at(datetime(2026, 9, 22, 5, 0, tzinfo=UTC))
    [placed] = sandbox.get_orderbook(1)

    assert get_order_status(sandbox, placed.order_id).status is OrderStatus.FILLED
    with pytest.raises(UnknownOrderError, match="get_orderbook"):
        get_order_status(sandbox, "SBNOPE")
