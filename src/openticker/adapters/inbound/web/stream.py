"""The web app's live stream, `/api/v1/stream` (ADR 32 in docs/adr).

One WebSocket per open tab. The page subscribes to the instruments it shows;
the hub sends each one's price at once, then every change, at most four
times a second. It also says where prices come from (the live feed, quiet,
market closed, no broker session), and sends every new audit log entry
within half a second: an agent's stdio MCP server is another process with
its own event bus, so the audit log, which every process writes, is the one
place its orders show up.

Subscriptions are counted across connections, and the daemon's feed streams
every instrument some page wants (`watched()`). A new one sets the feed's
`wake` event, so its first live tick comes within about a second instead of
after the feed's next five-second pass.
"""

import asyncio
import json
import logging
import threading
import time
from collections.abc import Callable, Sequence
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from pydantic import BaseModel, ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect, WebSocketState

from openticker.adapters.brokers.registry import BrokerConfigError
from openticker.adapters.inbound.daemon.prices import LatestPrices
from openticker.adapters.inbound.mcp_models import AuditEntryResult, InstrumentRef
from openticker.adapters.inbound.web.models import (
    MAX_SUBSCRIPTIONS,
    ClientMessage,
    ErrorMessage,
    EventMessage,
    FeedStatusResult,
    HelloMessage,
    Ping,
    PongMessage,
    StatusMessage,
    Subscribe,
    TickMessage,
)
from openticker.ports.errors import BrokerError
from openticker.ports.models import EXCHANGE_TIMEZONE, Instrument, Quote, Tick
from openticker.use_cases.feed_status import FeedStatus
from openticker.use_cases.get_audit_log import latest_audit_id, new_audit_entries
from openticker.use_cases.resolve_instrument import UnknownInstrumentError, resolve_instrument

__all__ = ["MAX_SUBSCRIPTIONS", "StreamHub"]

log = logging.getLogger(__name__)

StreamKey = tuple[str, str]  # (exchange, symbol)
TICK_EVERY = 0.25  # seconds
STATUS_EVERY = 1.0  # a page must see "live" soon after its first tick
TAIL_EVERY = 0.5  # how often the audit log is read for new entries
TAIL_BATCH = 200
SESSION_CHECK_EVERY = timedelta(minutes=1)  # also keeps an open tab's session alive
SIGNED_OUT = 4401  # the close code the page reads as "sign in again"


@dataclass(eq=False)  # one per socket, kept in a set
class _Connection:
    socket: WebSocket
    alive: Callable[[], bool]
    checked_at: datetime
    after_event: int = 0  # the last audit entry this page has been sent, or had at hello
    keys: dict[StreamKey, Instrument] = field(default_factory=dict)
    sent: dict[StreamKey, datetime] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send(self, message: BaseModel) -> None:
        async with self.lock:
            await self.socket.send_text(message.model_dump_json())


class StreamHub:
    def __init__(
        self,
        prices: LatestPrices,
        quote: Callable[[Sequence[Instrument]], list[Quote]],
        status: Callable[[], FeedStatus],
        wake: threading.Event,
        clock: Callable[[], datetime],
    ) -> None:
        """`quote` fetches quotes from the broker, for the previous close a
        change is measured from and a price before the first tick; `wake` is
        the feed's."""
        self._prices = prices
        self._quote = quote
        self._status = status
        self._wake = wake
        self._clock = clock
        self._lock = threading.Lock()
        self._counts: dict[StreamKey, int] = {}
        self._instruments: dict[StreamKey, Instrument] = {}
        self._closes: dict[StreamKey, tuple[date, float | None]] = {}
        self._connections: set[_Connection] = set()
        self._last_event: int | None = None  # the tail's cursor while any page is open
        self._tail_task: asyncio.Task[None] | None = None

    def watched(self) -> list[Instrument]:
        """Every instrument an open page wants streamed. Thread-safe."""
        with self._lock:
            return [self._instruments[key] for key in self._counts]

    async def serve(self, socket: WebSocket, alive: Callable[[], bool]) -> None:
        """One accepted connection until it closes. `alive` says whether its
        browser session still stands; it is asked once a minute."""
        conn = _Connection(socket, alive, self._clock())
        tasks: set[asyncio.Task[None]] = set()
        await self._join(conn)
        try:
            # A page can close before its first messages: it still leaves.
            await conn.send(
                HelloMessage(
                    server_time=self._clock().astimezone(EXCHANGE_TIMEZONE),
                    last_event_id=conn.after_event,
                )
            )
            status = await asyncio.to_thread(self._status)
            await conn.send(StatusMessage(feed=FeedStatusResult.of(status)))
            tasks = {
                asyncio.create_task(self._receive(conn)),
                asyncio.create_task(self._send_changes(conn, status)),
            }
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                error = None if task.cancelled() else task.exception()
                if error is not None and not isinstance(error, (WebSocketDisconnect, RuntimeError)):
                    log.error("stream connection failed", exc_info=error)
        except (WebSocketDisconnect, RuntimeError):
            pass  # closed before its first messages went
        finally:
            for task in tasks:
                task.cancel()
                with suppress(asyncio.CancelledError, WebSocketDisconnect, RuntimeError):
                    await task
            self._connections.discard(conn)
            self._release(list(conn.keys))

    async def _join(self, conn: _Connection) -> None:
        """Adds a page to those the tail sends to, from the tail's cursor on:
        it gets every entry after the one its hello names, once."""
        if self._last_event is None:
            latest = await asyncio.to_thread(latest_audit_id)
            if self._last_event is None:  # another page may have joined meanwhile
                self._last_event = latest
        conn.after_event = self._last_event
        self._connections.add(conn)
        if self._tail_task is None or self._tail_task.done():
            self._tail_task = asyncio.create_task(self._tail())

    async def _tail(self) -> None:
        """Reads the audit log for new entries every TAIL_EVERY while any page
        is open, and sends each to every page. With none open it stops and
        forgets its cursor: the next page starts from the newest entry."""
        try:
            while self._connections:
                await asyncio.sleep(TAIL_EVERY)
                after = self._last_event or 0
                try:
                    entries = await asyncio.to_thread(new_audit_entries, after, TAIL_BATCH)
                except Exception:  # a locked database: the next pass reads again
                    log.exception("reading new audit entries failed")
                    continue
                if not entries:
                    continue
                self._last_event = entries[-1].id
                messages = [(e.id, EventMessage(entry=AuditEntryResult.of(e))) for e in entries]
                for conn in list(self._connections):
                    await self._send_events(conn, messages)
        finally:
            if not self._connections:
                self._last_event = None

    async def _send_events(
        self, conn: _Connection, messages: list[tuple[int, EventMessage]]
    ) -> None:
        for entry_id, message in messages:
            if entry_id <= conn.after_event:
                continue
            if conn.socket.client_state != WebSocketState.CONNECTED:
                return
            try:
                await conn.send(message)
            except (WebSocketDisconnect, RuntimeError):
                return  # its own tasks see the close and clean up
            conn.after_event = entry_id

    async def _receive(self, conn: _Connection) -> None:
        while True:
            text = await conn.socket.receive_text()
            try:
                message = ClientMessage.model_validate({"message": json.loads(text)}).message
            except (ValueError, ValidationError):
                await conn.send(
                    ErrorMessage(detail="expected subscribe, unsubscribe or ping as JSON")
                )
                continue
            if isinstance(message, Ping):
                await conn.send(PongMessage())
            elif isinstance(message, Subscribe):
                await self._subscribe(conn, message.instruments)
            else:
                dropped = [_key_of(ref) for ref in message.instruments]
                self._release([key for key in dropped if conn.keys.pop(key, None) is not None])
                for key in dropped:
                    conn.sent.pop(key, None)

    async def _subscribe(self, conn: _Connection, refs: Sequence[InstrumentRef]) -> None:
        wanted = {_key_of(ref): ref for ref in refs if _key_of(ref) not in conn.keys}
        if len(conn.keys) + len(wanted) > MAX_SUBSCRIPTIONS:
            await conn.send(
                ErrorMessage(detail=f"at most {MAX_SUBSCRIPTIONS} instruments per connection")
            )
            return
        found, unknown = await asyncio.to_thread(_resolve, list(wanted.values()))
        if unknown:
            await conn.send(
                ErrorMessage(detail="not in the instrument master: " + ", ".join(unknown))
            )
        added = {_key(instrument): instrument for instrument in found}
        conn.keys.update(added)
        if self._retain(added):
            self._wake.set()
        await self._fetch_closes(list(added.values()))
        for key in added:
            await self._send_price(conn, key)

    async def _send_changes(self, conn: _Connection, status: FeedStatus) -> None:
        next_status = time.monotonic() + STATUS_EVERY
        while True:
            await asyncio.sleep(TICK_EVERY)
            for key in list(conn.keys):
                await self._send_price(conn, key)
            if time.monotonic() >= next_status:
                next_status = time.monotonic() + STATUS_EVERY
                latest = await asyncio.to_thread(self._status)
                if _shown(latest) != _shown(status):
                    await conn.send(StatusMessage(feed=FeedStatusResult.of(latest)))
                status = latest
            now = self._clock()
            if now - conn.checked_at >= SESSION_CHECK_EVERY:
                conn.checked_at = now
                if not await asyncio.to_thread(conn.alive):
                    await conn.socket.close(SIGNED_OUT)
                    return

    async def _send_price(self, conn: _Connection, key: StreamKey) -> None:
        instrument = conn.keys.get(key)
        tick = self._prices.get(instrument) if instrument else None
        if tick is None or conn.sent.get(key) == tick.received_at:
            return
        conn.sent[key] = tick.received_at
        streamed = self._prices.streamed_at(tick.instrument) == tick.received_at
        close = self._closes.get(key, (None, None))[1]
        if conn.socket.client_state == WebSocketState.CONNECTED:
            await conn.send(TickMessage.of(tick, close, streamed))

    async def _fetch_closes(self, instruments: Sequence[Instrument]) -> None:
        """Quotes the ones without today's previous close: the close, and a
        price to show until the feed's first tick."""
        today = self._clock().astimezone(EXCHANGE_TIMEZONE).date()
        missing = [i for i in instruments if self._closes.get(_key(i), (None,))[0] != today]
        if not missing:
            return
        try:
            quotes = await asyncio.to_thread(self._quote, missing)
        except (BrokerError, BrokerConfigError) as exc:
            log.info("no quotes for the stream: %s", exc)
            return
        now = self._clock()
        for quote in quotes:
            self._closes[_key(quote.instrument)] = (today, quote.close)
        self._prices.update_polled([Tick(q.instrument, q.last_price, now) for q in quotes])

    def _retain(self, added: dict[StreamKey, Instrument]) -> bool:
        """Counts the new subscriptions; True when one wasn't streamed yet."""
        new = False
        with self._lock:
            for key, instrument in added.items():
                new = new or key not in self._counts
                self._counts[key] = self._counts.get(key, 0) + 1
                self._instruments[key] = instrument
        return new

    def _release(self, keys: Sequence[StreamKey]) -> None:
        with self._lock:
            for key in keys:
                count = self._counts.get(key, 0) - 1
                if count > 0:
                    self._counts[key] = count
                else:
                    self._counts.pop(key, None)
                    self._instruments.pop(key, None)


def _key(instrument: Instrument) -> StreamKey:
    return (instrument.exchange, instrument.symbol)


def _key_of(ref: InstrumentRef) -> StreamKey:
    return (ref.exchange, ref.symbol)


def _resolve(refs: Sequence[InstrumentRef]) -> tuple[list[Instrument], list[str]]:
    found: list[Instrument] = []
    unknown: list[str] = []
    for ref in refs:
        try:
            found.append(resolve_instrument(ref.symbol, ref.exchange))
        except UnknownInstrumentError:
            unknown.append(f"{ref.exchange}:{ref.symbol}")
    return found, unknown


def _shown(status: FeedStatus) -> tuple[object, ...]:
    """What the page shows of a status: every field but the last tick's time."""
    return (status.broker_connected, status.broker_expires_at, status.market_open, status.state)
