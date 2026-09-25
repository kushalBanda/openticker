from openticker.storage.sqlite import credentials_repo
from openticker.use_cases.connect_broker import connect_broker
from tests.fixtures.fake_broker import FakeBrokerPort


def test_connect_broker_persists_the_authenticated_credentials() -> None:
    result = connect_broker(FakeBrokerPort(), request_token="irrelevant-for-a-fake")

    assert result.broker == "fake"
    stored = credentials_repo.get_credentials("fake")
    assert stored == result
