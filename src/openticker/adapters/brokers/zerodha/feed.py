"""ZerodhaFeed: Kite Connect's WebSocket ticker as a MarketFeedPort (ADR 13
in docs/adr).

A background thread holds the connection: it subscribes in LTP mode, parses
binary packets into ticks, and reconnects with backoff, resubscribing
everything. A handshake refused with 403 means the session has expired;
the thread stops and `ticks()` raises `BrokerSessionError`.

The URL carries the access token, so neither it nor an exception's text that
might include it is ever logged.
"""

import json
import logging
import queue
import struct
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import Protocol

from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

from openticker.ports.errors import BrokerSessionError
from openticker.ports.models import Instrument, Tick

log = logging.getLogger(__name__)

TICKER_URL = "wss://ws.kite.trade"
_PRICE_DIVISOR = 100.0  # paise; true for every segment OpenTicker supports
_HEADER = struct.Struct(">H")
_TOKEN_AND_PRICE = struct.Struct(">iI")
_SILENCE_LIMIT = 10.0  # Kite sends a heartbeat every second; this long without one means dead
_MAX_BACKOFF = 30.0
_STABLE_SECONDS = 30.0  # a connection that lasted this long resets the backoff


class Connection(Protocol):
    def send(self, message: str) -> None: ...

    def recv(self, timeout: float | None = None) -> str | bytes: ...

    def close(self) -> None: ...


def _open(url: str) -> Connection:
    return connect(url, open_timeout=10, max_size=2**22)


def parse_ticks(
    message: bytes, instruments: Mapping[int, Instrument], received_at: datetime
) -> list[Tick]:
    """Every packet starts with the instrument token and last price, whatever
    its mode, so only those eight bytes are read. A 1-byte message is a
    heartbeat. Tokens not subscribed (a late packet after unsubscribing) are
    dropped, and so is a truncated packet."""
    if len(message) < 2:
        return []
    (count,) = _HEADER.unpack_from(message, 0)
    offset = 2
    ticks: list[Tick] = []
    for _ in range(count):
        if offset + _HEADER.size > len(message):
            break
        (length,) = _HEADER.unpack_from(message, offset)
        offset += _HEADER.size
        if length >= _TOKEN_AND_PRICE.size and offset + length <= len(message):
            token, price = _TOKEN_AND_PRICE.unpack_from(message, offset)
            instrument = instruments.get(token)
            if instrument is not None:
                ticks.append(Tick(instrument, price / _PRICE_DIVISOR, received_at))
        offset += length
    return ticks


class ZerodhaFeed:
    def __init__(
        self,
        api_key: str,
        access_token: str,
        open_connection: Callable[[str], Connection] = _open,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._url = f"{TICKER_URL}?api_key={api_key}&access_token={access_token}"
        self._open_connection = open_connection
        self._clock = clock
        self._lock = threading.Lock()
        self._wanted: dict[int, Instrument] = {}
        self._queue: queue.Queue[Tick] = queue.Queue()
        self._stopped = threading.Event()
        self._session_expired = False
        self._thread = threading.Thread(target=self._run, name="zerodha-feed", daemon=True)
        self._thread.start()

    def subscribe(self, instruments: Sequence[Instrument]) -> None:
        with self._lock:
            self._wanted.update({int(i.token): i for i in instruments})

    def unsubscribe(self, instruments: Sequence[Instrument]) -> None:
        with self._lock:
            for instrument in instruments:
                self._wanted.pop(int(instrument.token), None)

    def ticks(self, timeout: float) -> list[Tick]:
        if self._session_expired:
            raise BrokerSessionError(
                "Kite refused the session for live prices: log in again "
                "(get_broker_login_url, then connect_broker)"
            )
        try:
            first = self._queue.get(timeout=timeout)
        except queue.Empty:
            return []
        received = [first]
        while True:
            try:
                received.append(self._queue.get_nowait())
            except queue.Empty:
                return received

    def close(self) -> None:
        self._stopped.set()
        self._thread.join(timeout=5)

    def _run(self) -> None:
        backoff = 1.0
        while not self._stopped.is_set():
            try:
                connection = self._open_connection(self._url)
            except InvalidStatus as exc:
                if exc.response.status_code == 403:
                    log.warning("Kite ticker refused the session (403); stopping until a new login")
                    self._session_expired = True
                    return
                log.warning("Kite ticker handshake failed: HTTP %s", exc.response.status_code)
            except Exception as exc:  # noqa: BLE001 — any failure to connect is retried
                log.warning("Kite ticker connection failed: %s", type(exc).__name__)
            else:
                log.info("Kite ticker connected")
                started = time.monotonic()
                self._stream(connection)
                if time.monotonic() - started >= _STABLE_SECONDS:
                    backoff = 1.0
                    continue
            self._stopped.wait(backoff)
            backoff = min(backoff * 2, _MAX_BACKOFF)

    def _stream(self, connection: Connection) -> None:
        sent: dict[int, Instrument] = {}
        last_heard = time.monotonic()
        try:
            while not self._stopped.is_set():
                with self._lock:
                    wanted = dict(self._wanted)
                sent = self._sync_subscriptions(connection, sent, wanted)
                try:
                    message = connection.recv(timeout=1.0)
                except TimeoutError:
                    if time.monotonic() - last_heard > _SILENCE_LIMIT:
                        log.warning("Kite ticker silent for %.0fs; reconnecting", _SILENCE_LIMIT)
                        return
                    continue
                last_heard = time.monotonic()
                if isinstance(message, bytes):
                    for tick in parse_ticks(message, sent, self._clock()):
                        self._queue.put(tick)
                else:
                    self._on_text(message)
        except Exception as exc:  # noqa: BLE001 — a dropped connection is reconnected by _run
            log.warning("Kite ticker disconnected: %s", type(exc).__name__)
        finally:
            connection.close()

    def _sync_subscriptions(
        self, connection: Connection, sent: dict[int, Instrument], wanted: dict[int, Instrument]
    ) -> dict[int, Instrument]:
        added = [token for token in wanted if token not in sent]
        removed = [token for token in sent if token not in wanted]
        if added:
            connection.send(json.dumps({"a": "subscribe", "v": added}))
            connection.send(json.dumps({"a": "mode", "v": ["ltp", added]}))
        if removed:
            connection.send(json.dumps({"a": "unsubscribe", "v": removed}))
        return wanted

    def _on_text(self, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            return
        if isinstance(payload, dict) and payload.get("type") == "error":
            log.warning("Kite ticker error: %s", payload.get("data"))
