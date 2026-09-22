import json
import logging
import struct
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from websockets.datastructures import Headers
from websockets.exceptions import ConnectionClosedError, InvalidStatus
from websockets.http11 import Response

from openticker.adapters.brokers.zerodha.feed import ZerodhaFeed, parse_ticks
from openticker.ports.errors import BrokerSessionError
from openticker.ports.models import Tick
from tests.fixtures.fake_broker import FAKE_INSTRUMENT

AT = datetime(2026, 9, 22, 5, 0, tzinfo=UTC)
RELIANCE = replace(FAKE_INSTRUMENT, token="738561")
NIFTY = replace(FAKE_INSTRUMENT, symbol="NIFTY 50", token="256265")


def packets(*bodies: bytes) -> bytes:
    return struct.pack(">H", len(bodies)) + b"".join(
        struct.pack(">H", len(body)) + body for body in bodies
    )


def ltp(token: int, paise: int) -> bytes:
    return struct.pack(">iI", token, paise)


def test_parse_reads_token_and_price_whatever_the_packet_mode() -> None:
    quote_mode = ltp(256265, 2340905) + bytes(36)  # 44-byte quote packet
    by_token = {738561: RELIANCE, 256265: NIFTY}

    ticks = parse_ticks(packets(ltp(738561, 124830), quote_mode), by_token, AT)

    assert [(t.instrument.symbol, t.last_price, t.received_at) for t in ticks] == [
        ("RELIANCE", 1248.3, AT),
        ("NIFTY 50", 23409.05, AT),
    ]


def test_parse_ignores_heartbeats_unknown_tokens_and_truncated_packets() -> None:
    by_token = {738561: RELIANCE}

    assert parse_ticks(b"\x00", by_token, AT) == []
    assert parse_ticks(packets(ltp(999, 100)), by_token, AT) == []
    assert parse_ticks(packets(ltp(738561, 100))[:-3], by_token, AT) == []


class _Connection:
    """Replays `script`: bytes/str are received, an exception is raised, and
    running out means silence."""

    def __init__(self, script: list[object]) -> None:
        self.script = script
        self.sent: list[dict[str, object]] = []
        self.closed = False

    def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    def recv(self, timeout: float | None = None) -> str | bytes:
        if not self.script:
            time.sleep(0.01)
            raise TimeoutError
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, (str, bytes))
        return item

    def close(self) -> None:
        self.closed = True


def _opener(*outcomes: object) -> tuple[Callable[[str], _Connection], list[str]]:
    urls: list[str] = []
    remaining = list(outcomes)

    def open_connection(url: str) -> _Connection:
        urls.append(url)
        outcome = remaining.pop(0) if remaining else _Connection([])
        if isinstance(outcome, Exception):
            raise outcome
        assert isinstance(outcome, _Connection)
        return outcome

    return open_connection, urls


def _until(condition: Callable[[], object], seconds: float = 3.0) -> None:
    deadline = time.monotonic() + seconds
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        time.sleep(0.01)


def _refused() -> InvalidStatus:
    return InvalidStatus(Response(403, "Forbidden", Headers()))


def test_feed_subscribes_in_ltp_mode_and_delivers_ticks() -> None:
    connection = _Connection([])
    open_connection, urls = _opener(connection)
    feed = ZerodhaFeed("key", "token", open_connection, clock=lambda: AT)
    feed.subscribe([RELIANCE])

    _until(lambda: len(connection.sent) == 2)
    connection.script.append(packets(ltp(738561, 124830)))
    received: list[Tick] = []

    def arrived() -> bool:
        received.extend(feed.ticks(0.05))
        return bool(received)

    _until(arrived)
    feed.close()

    assert connection.sent == [
        {"a": "subscribe", "v": [738561]},
        {"a": "mode", "v": ["ltp", [738561]]},
    ]
    assert urls == ["wss://ws.kite.trade?api_key=key&access_token=token"]
    assert [tick.last_price for tick in received] == [1248.3]


def test_feed_reconnects_and_resubscribes_everything(caplog: pytest.LogCaptureFixture) -> None:
    dropped = _Connection([ConnectionClosedError(None, None)])
    second = _Connection([])
    open_connection, urls = _opener(dropped, OSError("unreachable"), second)
    feed = ZerodhaFeed("key", "secret-token", open_connection)
    feed.subscribe([RELIANCE, NIFTY])

    with caplog.at_level(logging.INFO):
        _until(lambda: len(second.sent) == 2, seconds=5)
    feed.close()

    assert len(urls) == 3 and dropped.closed
    assert second.sent[0] == {"a": "subscribe", "v": [738561, 256265]}
    assert "secret-token" not in caplog.text


def test_unsubscribe_is_sent() -> None:
    connection = _Connection([])
    feed = ZerodhaFeed("key", "token", _opener(connection)[0])
    feed.subscribe([RELIANCE, NIFTY])
    _until(lambda: len(connection.sent) == 2)

    feed.unsubscribe([NIFTY])
    _until(lambda: len(connection.sent) == 3)
    feed.close()

    assert connection.sent[2] == {"a": "unsubscribe", "v": [256265]}


def test_refused_session_stops_the_feed_and_says_log_in() -> None:
    open_connection, urls = _opener(_refused())
    feed = ZerodhaFeed("key", "token", open_connection)

    def refused() -> bool:
        try:
            feed.ticks(0.01)
        except BrokerSessionError:
            return True
        return False

    _until(refused)
    feed.close()

    assert len(urls) == 1  # no retrying a dead session
    with pytest.raises(BrokerSessionError, match="log in again"):
        feed.ticks(0.01)


def test_a_connection_that_drops_at_once_is_retried_with_backoff() -> None:
    open_connection, urls = _opener(
        *[_Connection([ConnectionClosedError(None, None)]) for _ in range(5)]
    )
    feed = ZerodhaFeed("key", "token", open_connection)

    time.sleep(0.5)
    feed.close()

    assert len(urls) == 1  # the next attempt waits a second, not zero
