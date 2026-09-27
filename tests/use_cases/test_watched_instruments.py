from dataclasses import replace

from openticker.core.orders.sandbox import FLAT, NetPosition
from openticker.ports.models import Exchange, Product
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from openticker.storage.sqlite.sandbox_repo import fill_transaction, save_position
from openticker.use_cases.watched_instruments import watched_instruments
from tests.fixtures.fake_broker import FAKE_INSTRUMENT

NIFTY = replace(FAKE_INSTRUMENT, symbol="NIFTY 50", token="256265")
INFY = replace(FAKE_INSTRUMENT, symbol="INFY", token="408065")


def test_open_positions_and_the_watch_list_are_streamed_once_each() -> None:
    upsert_instruments([FAKE_INSTRUMENT, NIFTY, INFY])
    with fill_transaction() as session:
        save_position(session, "NSE", "RELIANCE", Product.MIS, NetPosition(3, 1248.3, 748.98, 0.0))
        save_position(session, "NSE", "INFY", Product.CNC, FLAT)  # closed earlier

    watched = watched_instruments(
        [("NIFTY 50", Exchange.NSE), ("RELIANCE", Exchange.NSE), ("UNSYNCED", Exchange.NSE)]
    )

    assert [i.symbol for i in watched] == ["RELIANCE", "NIFTY 50"]


def test_pending_orders_are_streamed_too() -> None:
    from openticker.adapters.sandbox.broker import SandboxBroker, SandboxSettings
    from openticker.core.orders.models import OrderRequest, OrderType
    from openticker.ports.models import Side
    from tests.fixtures.priced_broker import PricedBroker

    upsert_instruments([FAKE_INSTRUMENT, INFY])
    SandboxBroker("fake", PricedBroker(100.0), SandboxSettings()).place_order(
        OrderRequest(INFY, Side.BUY, 1, Product.CNC, OrderType.LIMIT, 90.0, "mcp")
    )

    assert [i.symbol for i in watched_instruments([])] == ["INFY"]


def test_instruments_a_browser_watches_are_streamed_too() -> None:
    upsert_instruments([FAKE_INSTRUMENT, NIFTY])

    watched = watched_instruments(
        [("RELIANCE", Exchange.NSE)], browser=lambda: [NIFTY, FAKE_INSTRUMENT]
    )

    assert [i.symbol for i in watched] == ["RELIANCE", "NIFTY 50"]
