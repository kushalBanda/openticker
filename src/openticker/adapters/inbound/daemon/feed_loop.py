"""The daemon's live-price loop (ADR 13 in docs/adr): keeps the feed
subscribed to the watched instruments, moves ticks into LatestPrices, and
turns a refused broker session into one notification until prices return.

`step()` does one pass and is what the tests drive; `run()` repeats it.
"""

import logging
import threading
import time
from collections.abc import Callable

from openticker.adapters.brokers.registry import BrokerConfigError
from openticker.adapters.inbound.daemon.prices import LatestPrices
from openticker.events.bus import EventPublisher
from openticker.events.types import BrokerSessionExpired
from openticker.ports.errors import BrokerSessionError
from openticker.ports.market_feed_port import MarketFeedPort
from openticker.ports.models import Instrument

log = logging.getLogger(__name__)

RESUBSCRIBE_SECONDS = 5.0  # how often the watched set is re-read
RECONNECT_SECONDS = 60.0  # how long to wait before trying a refused session again
SUMMARY_SECONDS = 60.0


class FeedLoop:
    def __init__(
        self,
        broker: str,
        open_feed: Callable[[], MarketFeedPort],
        watched: Callable[[], list[Instrument]],
        prices: LatestPrices,
        events: EventPublisher,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._broker = broker
        self._open_feed = open_feed
        self._watched = watched
        self._prices = prices
        self._events = events
        self._clock = clock
        self._feed: MarketFeedPort | None = None
        self._subscribed: dict[tuple[str, str], Instrument] = {}
        self._next_open = 0.0
        self._next_resubscribe = 0.0
        self._next_summary = clock() + SUMMARY_SECONDS
        self._session_refused = False
        self._ticks_since_summary = 0
        self._seen: set[tuple[str, str]] = set()

    def run(self, stop: threading.Event) -> None:
        try:
            while not stop.is_set():
                if not self.step(timeout=1.0):
                    stop.wait(1.0)
        finally:
            self.close()

    def step(self, timeout: float) -> bool:
        """One pass. False when there is no feed to wait on."""
        now = self._clock()
        if self._feed is None:
            if now < self._next_open:
                return False
            self._open(now)
            if self._feed is None:
                return False
        feed = self._feed
        if now >= self._next_resubscribe:
            self._resubscribe(feed)
            self._next_resubscribe = now + RESUBSCRIBE_SECONDS
        try:
            ticks = feed.ticks(timeout)
        except BrokerSessionError as exc:
            self._refused(str(exc))
            self.close()
            return False
        if ticks:
            if self._session_refused:
                log.info("live prices from %s are back", self._broker)
                self._session_refused = False
            self._prices.update(ticks)
            self._ticks_since_summary += len(ticks)
            for tick in ticks:
                key = (tick.instrument.exchange, tick.instrument.symbol)
                if key not in self._seen:
                    self._seen.add(key)
                    log.info("first live price: %s %s", tick.instrument.symbol, tick.last_price)
        if now >= self._next_summary:
            self._summarize()
            self._next_summary = now + SUMMARY_SECONDS
        return True

    def close(self) -> None:
        if self._feed is not None:
            self._feed.close()
            self._feed = None
            self._subscribed = {}
        self._next_open = self._clock() + RECONNECT_SECONDS

    def _open(self, now: float) -> None:
        try:
            self._feed = self._open_feed()
        except BrokerSessionError as exc:
            self._refused(str(exc))
            self._next_open = now + RECONNECT_SECONDS
            return
        except BrokerConfigError as exc:
            log.error("live prices from %s are off: %s", self._broker, exc)
            self._next_open = now + RECONNECT_SECONDS
            return
        self._next_resubscribe = now

    def _resubscribe(self, feed: MarketFeedPort) -> None:
        wanted = {(i.exchange.value, i.symbol): i for i in self._watched()}
        added = [i for key, i in wanted.items() if key not in self._subscribed]
        removed = [i for key, i in self._subscribed.items() if key not in wanted]
        if added:
            feed.subscribe(added)
            log.info("streaming %s", ", ".join(i.symbol for i in added))
        if removed:
            feed.unsubscribe(removed)
        self._subscribed = wanted

    def _refused(self, detail: str) -> None:
        if self._session_refused:
            return
        self._session_refused = True
        log.warning("live prices from %s stopped: %s", self._broker, detail)
        self._events.publish(BrokerSessionExpired(broker=self._broker, detail=detail))

    def _summarize(self) -> None:
        latest = sorted(self._prices.snapshot(), key=lambda tick: tick.instrument.symbol)
        if latest:
            shown = ", ".join(f"{t.instrument.symbol} {t.last_price}" for t in latest[:10])
            log.info("%d ticks in the last minute; latest: %s", self._ticks_since_summary, shown)
        self._ticks_since_summary = 0
