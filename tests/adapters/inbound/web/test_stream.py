import asyncio
import json
import time
from datetime import timedelta
from typing import Any, cast

import pytest
from fastapi import WebSocket
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from openticker.adapters.inbound.web.stream import MAX_SUBSCRIPTIONS
from openticker.ports.models import Tick
from openticker.storage.sqlite.audit_repo import write_audit
from tests.adapters.inbound.web.conftest import NIFTY, NOW, OWN, Web
from tests.fixtures.fake_broker import FAKE_INSTRUMENT

PATH = "/api/v1/stream"
SAME_ORIGIN = {"origin": OWN}
NIFTY_REF = {"exchange": "NSE", "symbol": "NIFTY 50"}


def _with_cookie(web: Web, origin: str = OWN) -> dict[str, str]:
    """TestClient sends neither its cookies nor its base URL's host on a
    WebSocket; a browser does."""
    return {
        "host": "127.0.0.1:8750",
        "origin": origin,
        "cookie": f"ot_session={web.client.cookies['ot_session']}",
    }


def _open(web: Web) -> WebSocketTestSession:
    web.sign_in()
    return web.sockets.enter_context(web.client.websocket_connect(PATH, headers=_with_cookie(web)))


def _connected(web: Web) -> WebSocketTestSession:
    socket = _open(web)
    assert socket.receive_json()["type"] == "hello"
    assert socket.receive_json()["type"] == "status"
    return socket


def _next(socket: WebSocketTestSession, kind: str) -> dict[str, Any]:
    while True:
        message: dict[str, Any] = socket.receive_json()
        if message["type"] == kind:
            return message


def _barrier(socket: WebSocketTestSession) -> list[dict[str, Any]]:
    """Everything sent before a ping's pong."""
    socket.send_json({"type": "ping"})
    seen = []
    while (message := socket.receive_json())["type"] != "pong":
        seen.append(message)
    return seen


def test_socket_without_session_closed_4401(web: Web) -> None:
    headers = {"host": "127.0.0.1:8750", **SAME_ORIGIN}

    with (
        pytest.raises(WebSocketDisconnect) as closed,
        web.client.websocket_connect(PATH, headers=headers) as socket,
    ):
        socket.receive_json()

    assert closed.value.code == 4401


def test_socket_from_a_foreign_origin_closed_4403(web: Web) -> None:
    web.sign_in()
    headers = _with_cookie(web, origin="http://evil.example")

    with (
        pytest.raises(WebSocketDisconnect) as closed,
        web.client.websocket_connect(PATH, headers=headers) as socket,
    ):
        socket.receive_json()

    assert closed.value.code == 4403


def test_hello_then_status_on_connect(web: Web) -> None:
    socket = _open(web)

    hello, status = socket.receive_json(), socket.receive_json()

    assert hello["type"] == "hello"
    assert hello["server_time"] == "2026-09-22T09:30:00+05:30"
    assert status == {
        "type": "status",
        "feed": {
            "broker": "fake",
            "broker_connected": True,
            "broker_expires_at": None,
            "last_tick_at": None,
            "market_open": True,
            "state": "quiet",
        },
    }
    socket.close()


def test_subscribe_sends_latest_price_at_once_with_change_from_the_close(web: Web) -> None:
    web.prices.update([Tick(NIFTY, 110.0, NOW)])
    socket = _connected(web)

    socket.send_json({"type": "subscribe", "instruments": [NIFTY_REF]})
    tick = _next(socket, "tick")

    assert tick == {
        "type": "tick",
        "exchange": "NSE",
        "symbol": "NIFTY 50",
        "last_price": 110.0,
        "change": 10.0,
        "change_pct": 10.0,
        "as_of": "2026-09-22T09:30:00+05:30",
        "streamed": True,
    }
    socket.close()


def test_subscribe_without_a_live_price_sends_the_quote(web: Web) -> None:
    socket = _connected(web)

    socket.send_json({"type": "subscribe", "instruments": [NIFTY_REF]})
    tick = _next(socket, "tick")

    assert (tick["last_price"], tick["change"], tick["streamed"]) == (105.0, 5.0, False)
    socket.close()


def test_the_close_is_asked_for_once_per_instrument(web: Web) -> None:
    socket = _connected(web)

    socket.send_json({"type": "subscribe", "instruments": [NIFTY_REF]})
    _next(socket, "tick")
    socket.send_json({"type": "unsubscribe", "instruments": [NIFTY_REF]})
    socket.send_json({"type": "subscribe", "instruments": [NIFTY_REF]})
    _barrier(socket)

    assert web.quotes.asked == [["NIFTY 50"]]
    socket.close()


def test_only_changed_prices_sent(web: Web) -> None:
    web.prices.update([Tick(NIFTY, 110.0, NOW)])
    socket = _connected(web)
    socket.send_json({"type": "subscribe", "instruments": [NIFTY_REF]})
    _next(socket, "tick")

    time.sleep(0.6)
    assert _barrier(socket) == []
    web.prices.update([Tick(NIFTY, 111.5, NOW + timedelta(seconds=1))])

    assert _next(socket, "tick")["last_price"] == 111.5
    socket.close()


def test_ticks_throttled_to_four_per_second(web: Web) -> None:
    socket = _connected(web)
    socket.send_json({"type": "subscribe", "instruments": [NIFTY_REF]})
    _next(socket, "tick")

    started = time.monotonic()
    for step in range(40):
        web.prices.update([Tick(NIFTY, 100.0 + step, NOW + timedelta(milliseconds=25 * step))])
        time.sleep(0.025)
    seen = [m for m in _barrier(socket) if m["type"] == "tick"]
    elapsed = time.monotonic() - started

    assert 1 <= len(seen) <= int(elapsed * 4) + 1
    socket.close()


def test_new_subscription_sets_feed_wake(web: Web) -> None:
    socket = _connected(web)

    socket.send_json({"type": "subscribe", "instruments": [NIFTY_REF]})
    _next(socket, "tick")

    assert web.wake.is_set()
    socket.close()


def test_watched_includes_browser_subscriptions_until_released(web: Web) -> None:
    first, second = _connected(web), _connected(web)
    for socket in (first, second):
        socket.send_json({"type": "subscribe", "instruments": [NIFTY_REF]})
        _next(socket, "tick")

    first.send_json({"type": "unsubscribe", "instruments": [NIFTY_REF]})
    _barrier(first)
    assert web.hub.watched() == [NIFTY]

    second.close()
    deadline = time.monotonic() + 2
    while web.hub.watched() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert web.hub.watched() == []
    first.close()


def test_unknown_instruments_are_reported_and_the_rest_subscribed(web: Web) -> None:
    socket = _connected(web)

    socket.send_json(
        {"type": "subscribe", "instruments": [{"exchange": "NSE", "symbol": "NOPE"}, NIFTY_REF]}
    )
    messages = _barrier(socket)

    [error] = [m for m in messages if m["type"] == "error"]
    assert "NOPE" in error["detail"]
    assert [m["symbol"] for m in messages if m["type"] == "tick"] == ["NIFTY 50"]
    socket.close()


def test_over_200_subscriptions_refused(web: Web) -> None:
    socket = _connected(web)
    many = [{"exchange": "NSE", "symbol": f"S{n}"} for n in range(MAX_SUBSCRIPTIONS + 1)]

    socket.send_json({"type": "subscribe", "instruments": many})

    assert "200" in _next(socket, "error")["detail"]
    socket.close()


def test_a_bad_message_is_answered_not_fatal(web: Web) -> None:
    socket = _connected(web)

    socket.send_json({"type": "dance"})

    assert _next(socket, "error")["type"] == "error"
    assert _barrier(socket) == []
    socket.close()


def test_a_session_signed_out_elsewhere_closes_the_socket(web: Web) -> None:
    socket = _connected(web)
    web.client.post("/api/v1/session/sign-out-all", headers=SAME_ORIGIN)
    web.clock.now = NOW + timedelta(minutes=2)

    with pytest.raises(WebSocketDisconnect) as closed:
        for _ in range(100):
            socket.receive_json()

    assert closed.value.code == 4401


def test_reliance_and_nifty_tick_independently(web: Web) -> None:
    socket = _connected(web)
    socket.send_json(
        {"type": "subscribe", "instruments": [NIFTY_REF, {"exchange": "NSE", "symbol": "RELIANCE"}]}
    )
    first = {_next(socket, "tick")["symbol"], _next(socket, "tick")["symbol"]}

    web.prices.update([Tick(FAKE_INSTRUMENT, 2600.0, NOW + timedelta(seconds=1))])

    assert first == {"NIFTY 50", "RELIANCE"}
    assert _next(socket, "tick")["symbol"] == "RELIANCE"
    socket.close()


def _audit(event_type: str, triggered_by: str | None, **fields: object) -> None:
    """As another process writes it: straight into the audit log."""
    write_audit(event_type, NOW, triggered_by, json.dumps(fields))


def test_events_from_another_process_arrive_within_half_a_second(web: Web) -> None:
    socket = _connected(web)
    started = time.monotonic()
    _audit("OrderFilled", "mcp:claude-code", symbol="RELIANCE", side="BUY", quantity=5)

    event = _next(socket, "event")

    assert time.monotonic() - started < 1.0  # a pass every 0.5 s, and the socket
    entry = event["entry"]
    assert (entry["event_type"], entry["source"]) == ("OrderFilled", "claude-code")
    assert entry["details"] == {"symbol": "RELIANCE", "side": "BUY", "quantity": 5}


def test_hello_names_the_last_event_and_only_newer_ones_are_sent(web: Web) -> None:
    _audit("InstrumentSyncCompleted", None, broker="fake", count=9)
    socket = _open(web)
    hello = _next(socket, "hello")
    _audit("OrderPlaced", "ui", symbol="TCS")

    event = _next(socket, "event")

    assert event["entry"]["id"] == hello["last_event_id"] + 1
    assert event["entry"]["source"] == "you"


def test_every_open_page_gets_each_event_once(web: Web) -> None:
    first, second = _connected(web), _connected(web)
    _audit("StrategyStopped", "strategy:s1", name="Straddle")
    _audit("OrderFilled", "strategy:s1", symbol="NIFTY")

    for socket in (first, second):
        got = [_next(socket, "event")["entry"]["event_type"] for _ in range(2)]
        assert got == ["StrategyStopped", "OrderFilled"]
        assert not [m for m in _barrier(socket) if m["type"] == "event"]


class _GoneSocket:
    """A page closed before its first message could be sent."""

    async def send_text(self, text: str) -> None:
        raise WebSocketDisconnect(code=1006)


def test_a_page_gone_before_its_hello_leaves_the_hub(web: Web) -> None:
    socket = cast(WebSocket, _GoneSocket())

    asyncio.run(web.hub.serve(socket, alive=lambda: True))

    assert web.hub._connections == set()  # the tail sends to nobody
