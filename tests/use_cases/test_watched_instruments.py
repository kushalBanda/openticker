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
