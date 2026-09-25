import threading
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

import pytest

from openticker.adapters.inbound.daemon.charge_check_loop import ChargeCheckLoop
from openticker.core.orders.charge_check import ChargeSample
from openticker.core.orders.charges import Charges
from openticker.ports.broker_port import BrokerPort
from openticker.ports.errors import BrokerSessionError
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from tests.fixtures.fake_broker import FAKE_INSTRUMENT, FakeBrokerPort

MORNING = datetime(2026, 9, 22, 4, 0, tzinfo=UTC)  # 09:30 IST


class _Events:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


class _Counting(FakeBrokerPort):
    def __init__(self) -> None:
        self.asked = 0
        self.session_ok = True

    def get_charges(self, orders: Sequence[ChargeSample]) -> list[Charges]:
        if not self.session_ok:
            raise BrokerSessionError("reconnect the broker")
        self.asked += 1
        return super().get_charges(orders)


@pytest.fixture(autouse=True)
def _master() -> None:
    upsert_instruments([FAKE_INSTRUMENT])


def _loop(broker: BrokerPort, now: list[datetime]) -> ChargeCheckLoop:
    return ChargeCheckLoop("fake", lambda: broker, _Events(), clock=lambda: now[0])


def test_checks_once_a_day() -> None:
    broker, now = _Counting(), [MORNING]
    loop = _loop(broker, now)

    loop.step()
    asked_first = broker.asked
    now[0] = MORNING + timedelta(hours=6)
    loop.step()
    assert broker.asked == asked_first  # same day: not again

    now[0] = MORNING + timedelta(days=1)
    loop.step()
    assert asked_first > 0 and broker.asked == 2 * asked_first


def test_a_check_that_could_not_run_is_tried_again(caplog: pytest.LogCaptureFixture) -> None:
    broker, now = _Counting(), [MORNING]
    broker.session_ok = False
    loop = _loop(broker, now)

    loop.step()
    assert broker.asked == 0 and "not run: reconnect the broker" in caplog.text

    broker.session_ok = True
    now[0] = MORNING + timedelta(hours=1)
    loop.step()
    assert broker.asked > 0


def test_run_survives_an_unexpected_error_and_stops_when_asked() -> None:
    stop = threading.Event()

    def broken() -> BrokerPort:
        stop.set()  # one pass is enough
        raise RuntimeError("bug")

    loop = ChargeCheckLoop("fake", broken, _Events(), clock=lambda: MORNING)
    thread = threading.Thread(target=loop.run, args=(stop,))
    thread.start()
    thread.join(timeout=5)

    assert not thread.is_alive()
