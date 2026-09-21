from openticker.storage.sqlite import instruments_repo
from openticker.use_cases.sync_instruments import sync_instruments
from tests.fixtures.fake_broker import FAKE_INSTRUMENT, FakeBrokerPort


def test_sync_instruments_stores_broker_master() -> None:
    count = sync_instruments(FakeBrokerPort())

    assert count == 1
    stored = instruments_repo.get_instrument(FAKE_INSTRUMENT.symbol, FAKE_INSTRUMENT.exchange)
    assert stored == FAKE_INSTRUMENT
