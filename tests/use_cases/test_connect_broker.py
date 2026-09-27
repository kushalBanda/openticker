from openticker.events.types import BrokerConnected, BrokerDisconnected
from openticker.storage.sqlite import credentials_repo
from openticker.use_cases.connect_broker import connect_broker, disconnect_broker
from tests.fixtures.fake_broker import FakeBrokerPort


class _Events:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


def test_connect_broker_persists_the_authenticated_credentials() -> None:
    events = _Events()
    result = connect_broker(FakeBrokerPort(), "irrelevant-for-a-fake", events, "ui")

    assert result.broker == "fake"
    stored = credentials_repo.get_credentials("fake")
    assert stored == result
    [event] = events.events
    assert isinstance(event, BrokerConnected)
    assert (event.broker, event.triggered_by) == ("fake", "ui")


def test_disconnect_deletes_the_session_once() -> None:
    events = _Events()
    connect_broker(FakeBrokerPort(), "token", events, "ui")

    assert disconnect_broker("fake", events, "ui") is True
    assert credentials_repo.get_credentials("fake") is None
    assert disconnect_broker("fake", events, "ui") is False
    assert [type(e) for e in events.events] == [BrokerConnected, BrokerDisconnected]
