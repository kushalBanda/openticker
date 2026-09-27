"""openticker-serve as the web app's end-to-end tests run it: the fake broker,
a live feed that walks every subscribed price every 300 ms, and a clock
pinned to a Tuesday session that then runs at real speed. The real FeedLoop,
stream hub and sign-in run in between, so a price the page asks for travels
the same path it does in production.

    uv run python -m tests.fixtures.e2e_server --port 8751 --home <dir> --links <file>

Writes 40 sign-in links, one per line, to `--links` once it is serving.

The paper account starts with the positions of the Positions mock: a NIFTY
straddle and part of a NIFTY future held by two running strategies, the rest
of the future and RELIANCE placed from the web app, HDFCBANK by Claude.
"""

import argparse
import os
import random
import threading
import time
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
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
from openticker.composition import build_event_bus, order_broker
from openticker.core.orders.models import OrderRequest, OrderStatus, OrderType
from openticker.core.strategies.runs import LegStatus, Run, RunLeg, RunStatus
from openticker.ports.models import (
    Credentials,
    Exchange,
    Instrument,
    InstrumentType,
    Product,
    Quote,
    Side,
    Tick,
)
from openticker.storage.calendar_file import load_calendar
from openticker.storage.sqlite import runs_repo
from openticker.storage.sqlite.credentials_repo import save_credentials
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from openticker.storage.sqlite.strategies_repo import insert_strategy, write_transaction
from openticker.use_cases.feed_status import feed_status
from openticker.use_cases.place_order import place_order
from openticker.use_cases.watched_instruments import watched_instruments
from openticker.use_cases.web_sessions import create_sign_in_link
from tests.fixtures.fake_broker import FAKE_INSTRUMENT, FakeBrokerPort
from tests.fixtures.strategies import STRADDLE

SESSION_START = datetime(2026, 9, 22, 5, 0, tzinfo=UTC)  # Tuesday 10:30 IST
MONTHLY = date(2026, 9, 29)
CLOSES = {
    "NIFTY 50": 24708.75,
    "NIFTY BANK": 53202.50,
    "SENSEX": 81103.71,
    "RELIANCE": 2931.50,
    "HDFCBANK": 1652.10,
    "NIFTY27OCT26FUT": 24858.20,
    "NIFTY29SEP2624800CE": 142.30,
    "NIFTY29SEP2624800PE": 131.80,
}
INDICES = ("NIFTY 50", "NIFTY BANK", "SENSEX")
# Every price the fake broker quotes and the feed walks; indices start up on the day.
PRICES = {symbol: close * 1.004 if symbol in INDICES else close for symbol, close in CLOSES.items()}


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


def _derivative(
    symbol: str, kind: InstrumentType, expiry: date, strike: float | None
) -> Instrument:
    return replace(
        FAKE_INSTRUMENT,
        symbol=symbol,
        broker_symbol=symbol,
        exchange=Exchange.NFO,
        broker_exchange="NFO",
        token=f"e2e-{symbol}",
        expiry=expiry,
        strike=strike,
        lot_size=75,
        instrument_type=kind,
    )


FUT = _derivative("NIFTY27OCT26FUT", InstrumentType.FUT, date(2026, 10, 27), None)
CE = _derivative("NIFTY29SEP2624800CE", InstrumentType.CE, MONTHLY, 24800.0)
PE = _derivative("NIFTY29SEP2624800PE", InstrumentType.PE, MONTHLY, 24800.0)
HDFCBANK = replace(FAKE_INSTRUMENT, symbol="HDFCBANK", broker_symbol="HDFCBANK", token="e2e-hdfc")

INSTRUMENTS = [
    FAKE_INSTRUMENT,
    HDFCBANK,
    FUT,
    CE,
    PE,
    _index("NIFTY 50", Exchange.NSE, "256265"),
    _index("NIFTY BANK", Exchange.NSE, "260105"),
    _index("SENSEX", Exchange.BSE, "265"),
]


class E2EBroker(FakeBrokerPort):
    """The fake broker quoting the walking prices, a tick either side."""

    def get_instrument_master(self) -> list[Instrument]:
        return INSTRUMENTS

    def get_quote(self, instrument: Instrument) -> Quote:
        last = PRICES.get(instrument.symbol, 2500.0)
        return Quote(
            instrument,
            last,
            datetime.now(UTC),
            bid=round(last - instrument.tick_size, 2),
            ask=round(last + instrument.tick_size, 2),
            close=CLOSES.get(instrument.symbol),
        )


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
            step = PRICES[symbol] * self._random.uniform(-0.0004, 0.0004)
            PRICES[symbol] = round(PRICES[symbol] + step, 2)
            ticks.append(Tick(instrument, PRICES[symbol], self._clock()))
        return ticks

    def close(self) -> None:
        pass


def _seed(env: dict[str, str], clock: Clock) -> None:
    """The Positions mock's account (see the module docstring)."""
    sandbox = order_broker("fake", env, clock)
    events = build_event_bus({})

    def fill(instrument: Instrument, side: Side, quantity: int, product: Product, who: str) -> None:
        request = OrderRequest(instrument, side, quantity, product, OrderType.MARKET, None, who)
        result = place_order(request, sandbox, events, None, load_calendar(), clock())
        assert result.status is OrderStatus.FILLED, result.reason

    def run(name: str, product: Product, legs: Sequence[tuple[Instrument, Side, int]]) -> None:
        strategy = insert_strategy(name, STRADDLE, clock())
        for instrument, side, quantity in legs:
            fill(instrument, side, quantity, product, f"strategy:{strategy.id}")
        started = Run(
            id=runs_repo.new_run_id(),
            strategy_id=strategy.id,
            broker="fake",
            product=product,
            status=RunStatus.OPEN,
            trigger="ui",
            started_at=clock(),
            legs=tuple(
                RunLeg(f"leg{n}", leg.symbol, leg.exchange, side, units, LegStatus.OPEN)
                for n, (leg, side, units) in enumerate(legs, 1)
            ),
        )
        with write_transaction() as session:
            runs_repo.insert_run(session, started)

    run("NIFTY short straddle", Product.MIS, [(CE, Side.SELL, 75), (PE, Side.SELL, 75)])
    run("NIFTY futures trend", Product.NRML, [(FUT, Side.BUY, 75)])
    fill(FUT, Side.BUY, 75, Product.NRML, "ui")
    fill(FAKE_INSTRUMENT, Side.BUY, 10, Product.MIS, "ui")
    fill(HDFCBANK, Side.SELL, 20, Product.MIS, "mcp:claude-code")
    events.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8751)
    parser.add_argument("--home", required=True)
    parser.add_argument("--links", required=True)
    args = parser.parse_args()
    os.environ["OPENTICKER_HOME"] = args.home

    registry.register("fake", E2EBroker)
    upsert_instruments(INSTRUMENTS)
    clock = Clock()
    save_credentials(Credentials("fake", "e2e", None, clock() + timedelta(hours=8)))
    env = {"SANDBOX_STARTING_CAPITAL": "2500000"}
    _seed(env, clock)

    events = build_event_bus({})
    prices = LatestPrices()
    wake = threading.Event()
    stop = threading.Event()

    def quote(instruments: Sequence[Instrument]) -> list[Quote]:
        return [E2EBroker().get_quote(i) for i in instruments if i.symbol in PRICES]

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
    app = create_app(events, env, clock=clock, hub=hub, web=web)
    links = [create_sign_in_link(web.own_origin, clock()) for _ in range(40)]
    Path(args.links).write_text("\n".join(links) + "\n")
    try:
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        stop.set()
        events.close()


if __name__ == "__main__":
    main()
