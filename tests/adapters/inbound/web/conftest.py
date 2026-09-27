"""The web app on a test client: the fake broker, a pinned clock that tests
can move, a built app in a temporary folder, and a way to sign in."""

import threading
from collections.abc import Iterator, Sequence
from contextlib import ExitStack
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from openticker.adapters.brokers import registry
from openticker.adapters.inbound.daemon.prices import LatestPrices
from openticker.adapters.inbound.rest_api import create_app
from openticker.adapters.inbound.web.auth import WebSettings
from openticker.adapters.inbound.web.stream import StreamHub
from openticker.composition import build_event_bus
from openticker.events.bus import EventBus
from openticker.ports.models import Instrument, Quote
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from openticker.use_cases.feed_status import FeedStatus
from openticker.use_cases.web_sessions import create_sign_in_link
from tests.fixtures.fake_broker import FAKE_INSTRUMENT, FakeBrokerPort

NOW = datetime(2026, 9, 22, 4, 0, tzinfo=UTC)  # Tuesday 09:30 IST
OWN = "http://127.0.0.1:8750"
NIFTY = replace(FAKE_INSTRUMENT, symbol="NIFTY 50", token="256265")


@dataclass
class Clock:
    now: datetime = NOW

    def __call__(self) -> datetime:
        return self.now


@dataclass
class Quotes:
    """What the broker quotes, and every batch it was asked for."""

    close: float = 100.0
    asked: list[list[str]] = field(default_factory=list)

    def __call__(self, instruments: Sequence[Instrument]) -> list[Quote]:
        self.asked.append([i.symbol for i in instruments])
        return [Quote(i, self.close + 5, NOW, close=self.close) for i in instruments]


@dataclass
class Web:
    client: TestClient
    clock: Clock
    prices: LatestPrices
    hub: StreamHub
    wake: threading.Event
    quotes: Quotes
    dist: Path
    sockets: ExitStack  # open WebSocket sessions, closed before the client

    def sign_in(self) -> TestClient:
        """Signs the client in through a fresh link, as a browser would."""
        link = urlsplit(create_sign_in_link(OWN, self.clock()))
        response = self.client.get(f"{link.path}?{link.query}", follow_redirects=False)
        assert response.status_code == 303, response.text
        return self.client


def status() -> FeedStatus:
    return FeedStatus("fake", True, None, None, True, "quiet")


@pytest.fixture(autouse=True)
def _fake_broker_registered() -> Iterator[None]:
    registry.register("fake", FakeBrokerPort)
    yield
    del registry.BROKER_REGISTRY["fake"]


@pytest.fixture
def events() -> Iterator[EventBus]:
    bus = build_event_bus({})
    yield bus
    bus.close()


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    built = tmp_path / "dist"
    (built / "assets").mkdir(parents=True)
    (built / "index.html").write_text("<!doctype html><title>OpenTicker</title><div id=root>")
    (built / "assets" / "app-3f9a.js").write_text("console.log('app')")
    return built


@pytest.fixture
def web(events: EventBus, dist: Path) -> Iterator[Web]:
    upsert_instruments([FAKE_INSTRUMENT, NIFTY])
    clock, prices, wake, quotes = Clock(), LatestPrices(), threading.Event(), Quotes()
    hub = StreamHub(prices, quotes, status, wake, clock)
    settings = WebSettings(own_origin=OWN, port=8750, dev_origin=None, dist=dist)
    app = create_app(events, {}, clock=clock, hub=hub, web=settings)
    with TestClient(app, base_url=OWN) as client, ExitStack() as sockets:
        yield Web(client, clock, prices, hub, wake, quotes, dist, sockets)
