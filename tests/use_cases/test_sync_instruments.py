from openticker.events.types import InstrumentSyncCompleted
from openticker.storage.sqlite import instruments_repo
from openticker.use_cases.sync_instruments import sync_instruments
from tests.fixtures.fake_broker import FAKE_INSTRUMENT, FakeBrokerPort


class _RecordingPublisher:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


def test_sync_instruments_stores_broker_master_and_publishes_completion() -> None:
    publisher = _RecordingPublisher()

    count = sync_instruments("fake", FakeBrokerPort(), publisher)

    assert count == 1
    stored = instruments_repo.get_instrument(FAKE_INSTRUMENT.symbol, FAKE_INSTRUMENT.exchange)
    assert stored == FAKE_INSTRUMENT
    [event] = publisher.events
    assert isinstance(event, InstrumentSyncCompleted)
    assert (event.broker, event.count) == ("fake", 1)
