import threading
from dataclasses import replace
from datetime import UTC, datetime

from openticker.adapters.brokers.registry import BrokerConfigError
from openticker.adapters.inbound.daemon.feed_loop import RECONNECT_SECONDS, FeedLoop
from openticker.adapters.inbound.daemon.prices import LatestPrices
from openticker.events.types import BrokerSessionExpired
from openticker.ports.errors import BrokerSessionError
from openticker.ports.market_feed_port import MarketFeedPort
from openticker.ports.models import Instrument, Tick
from tests.fixtures.fake_broker import FAKE_INSTRUMENT
from tests.fixtures.fake_feed import FakeFeed

AT = datetime(2026, 9, 22, 5, 0, tzinfo=UTC)
NIFTY = replace(FAKE_INSTRUMENT, symbol="NIFTY 50", token="256265")


class _Events:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class _Harness:
    def __init__(self, watched: list[Instrument]) -> None:
        self.watched = watched
        self.feeds: list[FakeFeed] = []
        self.refuse_open = False
        self.prices = LatestPrices()
        self.events = _Events()
        self.clock = _Clock()
        self.loop = FeedLoop(
            "zerodha", self.open_feed, lambda: self.watched, self.prices, self.events, self.clock
        )

    def open_feed(self) -> MarketFeedPort:
        if self.refuse_open:
            raise BrokerSessionError("zerodha is not connected")
        self.feeds.append(FakeFeed())
        return self.feeds[-1]


def test_ticks_for_watched_instruments_become_latest_prices() -> None:
    harness = _Harness([FAKE_INSTRUMENT, NIFTY])
    harness.loop.step(0)
    harness.feeds[0].batches.append([Tick(NIFTY, 23409.05, AT)])

    harness.loop.step(0)

    assert set(harness.feeds[0].subscribed) == {"RELIANCE", "NIFTY 50"}
    tick = harness.prices.get(NIFTY)
    assert tick is not None and tick.last_price == 23409.05
    assert harness.prices.get(FAKE_INSTRUMENT) is None


def test_subscriptions_follow_the_watched_set() -> None:
    harness = _Harness([FAKE_INSTRUMENT])
    harness.loop.step(0)
    harness.watched = [NIFTY]

    harness.loop.step(0)  # not yet: the set is re-read every few seconds
    assert set(harness.feeds[0].subscribed) == {"RELIANCE"}
    harness.clock.now += 5
    harness.loop.step(0)

    assert set(harness.feeds[0].subscribed) == {"NIFTY 50"}


def test_a_refused_session_is_notified_once_and_retried_later() -> None:
    harness = _Harness([FAKE_INSTRUMENT])
    harness.loop.step(0)
    harness.feeds[0].refused = True

    harness.loop.step(0)
    harness.loop.step(0)  # waits: no reopening before the retry interval
    harness.clock.now += RECONNECT_SECONDS
    harness.feeds.append(FakeFeed())
    harness.refuse_open = True
    harness.loop.step(0)  # still not connected: no second notification

    assert harness.feeds[0].closed
    assert [type(e) for e in harness.events.events] == [BrokerSessionExpired]
    assert "session refused" in harness.events.events[0].detail  # type: ignore[attr-defined]


def test_prices_coming_back_rearm_the_notification() -> None:
    harness = _Harness([FAKE_INSTRUMENT])
    harness.refuse_open = True
    harness.loop.step(0)
    harness.refuse_open = False
    harness.clock.now += RECONNECT_SECONDS
    harness.loop.step(0)
    harness.feeds[0].batches.append([Tick(FAKE_INSTRUMENT, 1248.3, AT)])
    harness.loop.step(0)

    harness.feeds[0].refused = True
    harness.loop.step(0)

    assert [type(e) for e in harness.events.events] == [BrokerSessionExpired, BrokerSessionExpired]


def test_missing_broker_settings_are_logged_not_notified() -> None:
    def no_settings() -> MarketFeedPort:
        raise BrokerConfigError("KITE_API_KEY / KITE_API_SECRET are not set")

    events = _Events()
    loop = FeedLoop("zerodha", no_settings, list, LatestPrices(), events, _Clock())

    assert loop.step(0) is False
    assert events.events == []


def test_wake_resubscribes_before_the_5s_period() -> None:
    wake = threading.Event()
    harness = _Harness([FAKE_INSTRUMENT])
    harness.loop = FeedLoop(
        "zerodha",
        harness.open_feed,
        lambda: harness.watched,
        harness.prices,
        harness.events,
        harness.clock,
        wake=wake,
    )
    harness.loop.step(0)
    harness.watched = [FAKE_INSTRUMENT, NIFTY]

    wake.set()
    harness.loop.step(0)

    assert set(harness.feeds[0].subscribed) == {"RELIANCE", "NIFTY 50"}
    assert not wake.is_set()
