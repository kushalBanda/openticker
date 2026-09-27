"""openticker-serve as the web app's end-to-end tests run it: the fake broker,
a live feed that walks every subscribed price every 300 ms, and a clock
pinned to a Tuesday session that then runs at real speed. The real FeedLoop,
stream hub and sign-in run in between, so a price the page asks for travels
the same path it does in production.

    uv run python -m tests.fixtures.e2e_server --port 8751 --home <dir> --links <file>

Writes 40 sign-in links, one per line, to `--links` once it is serving.
"""

import argparse
import os
import random
import threading
import time
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path

import uvicorn

from openticker.adapters.brokers import registry
from openticker.adapters.inbound.daemon.feed_loop import FeedLoop
from openticker.adapters.inbound.daemon.prices import LatestPrices
from openticker.adapters.inbound.rest_api import create_app
from openticker.adapters.inbound.web.app import DIST
from openticker.adapters.inbound.web.auth import WebSettings
from openticker.adapters.inbound.web.stream import StreamHub
from openticker.composition import build_event_bus
from openticker.ports.models import Credentials, Exchange, Instrument, InstrumentType, Quote, Tick
from openticker.storage.sqlite.credentials_repo import save_credentials
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from openticker.use_cases.feed_status import feed_status
from openticker.use_cases.watched_instruments import watched_instruments
from openticker.use_cases.web_sessions import create_sign_in_link
from tests.fixtures.fake_broker import FAKE_INSTRUMENT, FakeBrokerPort

SESSION_START = datetime(2026, 9, 22, 5, 0, tzinfo=UTC)  # Tuesday 10:30 IST
CLOSES = {"NIFTY 50": 24708.75, "NIFTY BANK": 53202.50, "SENSEX": 81103.71, "RELIANCE": 2480.0}


def _index(symbol: str, exchange: Exchange, token: str) -> Instrument:
    return replace(
        FAKE_INSTRUMENT,
        symbol=symbol,
        broker_symbol=symbol,
        exchange=exchange,
        broker_exchange=exchange,
        token=token,
        instrument_type=InstrumentType.INDEX,
    )


INSTRUMENTS = [
    FAKE_INSTRUMENT,
    _index("NIFTY 50", Exchange.NSE, "256265"),
    _index("NIFTY BANK", Exchange.NSE, "260105"),
    _index("SENSEX", Exchange.BSE, "265"),
]


class Clock:
    def __init__(self) -> None:
        self._started = time.monotonic()

    def __call__(self) -> datetime:
        return SESSION_START + timedelta(seconds=time.monotonic() - self._started)


class WalkingFeed:
    """A MarketFeedPort whose prices take a small random step each 300 ms."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._subscribed: dict[str, Instrument] = {}
        self._prices = {symbol: close * 1.004 for symbol, close in CLOSES.items()}
        self._random = random.Random(7)

    def subscribe(self, instruments: Sequence[Instrument]) -> None:
        self._subscribed.update({i.symbol: i for i in instruments})

    def unsubscribe(self, instruments: Sequence[Instrument]) -> None:
        for instrument in instruments:
            self._subscribed.pop(instrument.symbol, None)

    def ticks(self, timeout: float) -> list[Tick]:
        time.sleep(min(timeout, 0.3))
        ticks = []
        for symbol, instrument in list(self._subscribed.items()):
            step = self._prices[symbol] * self._random.uniform(-0.0004, 0.0004)
            self._prices[symbol] = round(self._prices[symbol] + step, 2)
            ticks.append(Tick(instrument, self._prices[symbol], self._clock()))
        return ticks

    def close(self) -> None:
        pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8751)
    parser.add_argument("--home", required=True)
    parser.add_argument("--links", required=True)
    args = parser.parse_args()
    os.environ["OPENTICKER_HOME"] = args.home

    registry.register("fake", FakeBrokerPort)
    upsert_instruments(INSTRUMENTS)
    clock = Clock()
    save_credentials(Credentials("fake", "e2e", None, clock() + timedelta(hours=8)))

    events = build_event_bus({})
    prices = LatestPrices()
    wake = threading.Event()
    stop = threading.Event()

    def quote(instruments: Sequence[Instrument]) -> list[Quote]:
        return [
            Quote(i, CLOSES[i.symbol], clock(), close=CLOSES[i.symbol])
            for i in instruments
            if i.symbol in CLOSES
        ]

    hub = StreamHub(
        prices,
        quote,
        lambda: feed_status("fake", prices.last_streamed_at(), clock()),
        wake,
        clock,
    )
    feed = WalkingFeed(clock)
    loop = FeedLoop(
        "fake",
        lambda: feed,
        partial(watched_instruments, [], browser=hub.watched),
        prices,
        events,
        wake=wake,
    )
    threading.Thread(target=loop.run, args=(stop,), daemon=True).start()

    web = WebSettings(f"http://127.0.0.1:{args.port}", args.port, None, DIST)
    app = create_app(events, {}, clock=clock, hub=hub, web=web)
    links = [create_sign_in_link(web.own_origin, clock()) for _ in range(40)]
    Path(args.links).write_text("\n".join(links) + "\n")
    try:
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        stop.set()
        events.close()


if __name__ == "__main__":
    main()
