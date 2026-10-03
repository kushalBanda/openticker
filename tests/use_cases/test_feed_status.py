from datetime import UTC, datetime, timedelta

from openticker.ports.models import Credentials
from openticker.storage.sqlite.credentials_repo import save_credentials
from openticker.use_cases.feed_status import feed_status

OPEN = datetime(2026, 9, 22, 5, 0, tzinfo=UTC)  # Tuesday 10:30 IST
SUNDAY = datetime(2026, 9, 27, 5, 0, tzinfo=UTC)


def _connect(expires_at: datetime | None = None) -> None:
    save_credentials(
        Credentials("zerodha", "token", None, expires_at or OPEN + timedelta(hours=12))
    )


def test_no_broker_until_connected() -> None:
    status = feed_status("zerodha", OPEN, OPEN)

    assert status.state == "no-broker"
    assert not status.broker_connected


def test_an_expired_session_counts_as_no_broker() -> None:
    _connect(expires_at=OPEN - timedelta(minutes=1))

    assert feed_status("zerodha", OPEN, OPEN).state == "no-broker"


def test_live_while_ticks_arrive() -> None:
    _connect()

    status = feed_status("zerodha", OPEN - timedelta(seconds=3), OPEN)

    assert status.state == "live"
    assert status.broker_connected and status.market_open


def test_quiet_when_open_and_no_tick_for_10_seconds() -> None:
    _connect()

    assert feed_status("zerodha", OPEN - timedelta(seconds=11), OPEN).state == "quiet"
    assert feed_status("zerodha", None, OPEN).state == "quiet"


def test_closed_when_the_market_is() -> None:
    _connect(expires_at=SUNDAY + timedelta(hours=1))

    status = feed_status("zerodha", None, SUNDAY)

    assert status.state == "closed"
    assert not status.market_open
