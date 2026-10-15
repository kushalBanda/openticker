"""openticker-serve as the web app's end-to-end tests run it: the fake broker,
a live feed that walks every subscribed price every 300 ms, and a clock
pinned to a Tuesday session that then runs at real speed. The real FeedLoop,
stream hub and sign-in run in between, so a price the page asks for travels
the same path it does in production.

    uv run python -m tests.fixtures.e2e_server --port 8751 --home <dir> --links <file>

Writes 160 sign-in links, one per line, to `--links` once it is serving.

The broker's login page is served on the next port, under `localhost`, so
its redirect back reaches the app from another site, as Kite's does.

The paper account starts with the positions of the Positions mock: a NIFTY
straddle and part of a NIFTY future held by two running strategies, the rest
of the future and RELIANCE placed from the web app, HDFCBANK by Claude. The
Strategies mock's other three strategies, and every strategy's history,
come from `e2e_strategies`. Its
order book is the Orders mock's: a resting HDFCBANK limit, a hosted script's
RELIANCE stop, Codex's refused NIFTY future and a cancelled RELIANCE limit.
Its trades add a TCS round trip today, and one yesterday from before fills
kept their realized P&L and charge breakdown. Hosted scripts run for real
(`e2e_hosted` seeds them, the MCP clients seen and more review jobs).
"""

import argparse
import bisect
import functools
import math
import os
import random
import sys
import threading
import time
import zlib
from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, tzinfo
from datetime import time as clock_time
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import uvicorn
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from openticker.adapters.agents.harness import HarnessProcesses
from openticker.adapters.brokers import registry
from openticker.adapters.inbound import mcp_server
from openticker.adapters.inbound.daemon.feed_loop import FeedLoop
from openticker.adapters.inbound.daemon.prices import LatestPrices
from openticker.adapters.inbound.daemon.script_loop import ScriptLoop
from openticker.adapters.inbound.mcp_scoped import MCP_PATH, WithMcp
from openticker.adapters.inbound.rest_api import create_app
from openticker.adapters.inbound.web.app import DIST
from openticker.adapters.inbound.web.auth import WebSettings
from openticker.adapters.inbound.web.stream import StreamHub
from openticker.adapters.scripts.supervisor import ProcessSupervisor
from openticker.composition import build_event_bus, order_broker, script_limits
from openticker.core.agents.jobs import (
    AgentJob,
    AgentJobEndReason,
    AgentJobKind,
    AgentJobStatus,
    AgentSettings,
    Harness,
)
from openticker.core.agents.threads import Folder
from openticker.core.agents.transcript import Usage
from openticker.core.options.chain import years_to_expiry
from openticker.core.options.greeks import black76_price
from openticker.core.orders.models import OrderRequest, OrderResult, OrderStatus, OrderType
from openticker.core.pnl import DayPnl, IntradayPoint
from openticker.core.strategies.models import (
    LegSpec,
    OptionsStrategySpec,
    SignalLeg,
    StrategySpec,
)
from openticker.core.strategies.runs import LegStatus, Run, RunLeg, RunStatus, leg_risk
from openticker.events import types as event_types
from openticker.events.bus import EventPublisher
from openticker.events.subscribers.audit_log import record_event
from openticker.events.types import ManagerNumbersChanged, ManagerPlanSet
from openticker.ports.agent_job_port import AgentOutcome
from openticker.ports.models import (
    EXCHANGE_TIMEZONE,
    Bar,
    Credentials,
    DepthLevel,
    Exchange,
    Instrument,
    InstrumentType,
    MarginRequirement,
    MarketDepth,
    Product,
    Quote,
    Side,
    Tick,
)
from openticker.storage.calendar_file import load_calendar
from openticker.storage.sqlite import agent_jobs_repo, agent_threads_repo, runs_repo
from openticker.storage.sqlite.credentials_repo import save_credentials
from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from openticker.storage.sqlite.models import AgentJobRow, SandboxTradeRow
from openticker.storage.sqlite.pnl_repo import upsert_day, upsert_point
from openticker.storage.sqlite.strategies_repo import (
    insert_strategy,
    list_strategies,
    write_transaction,
)
from openticker.storage.sqlite.watchlists_repo import WatchlistItem, add_items, insert_watchlist
from openticker.use_cases.agents.manager import queue_due_manager_wake
from openticker.use_cases.agents.settings import resolved_settings
from openticker.use_cases.agents.supervise import (
    AgentContext,
    start_next_chat_turn,
    start_next_job,
    watch_jobs,
)
from openticker.use_cases.cancel_order import cancel_order
from openticker.use_cases.feed_status import feed_status
from openticker.use_cases.place_order import place_order
from openticker.use_cases.scripts.manage import upload_script
from openticker.use_cases.watched_instruments import watched_instruments
from openticker.use_cases.web_sessions import create_sign_in_link
from tests.fixtures.e2e_brain import seed_brain
from tests.fixtures.e2e_hosted import (
    REL_TRAIL,
    seed_agents,
    seed_chat,
    seed_gone_chat,
    seed_scripts,
)
from tests.fixtures.e2e_strategies import STRADDLE_E2E, TREND, seed_strategies
from tests.fixtures.fake_broker import FAKE_INSTRUMENT, FakeBrokerPort

SESSION_START = datetime(2026, 9, 22, 5, 0, tzinfo=UTC)  # Tuesday 10:30 IST
E2E_ENV = {"SANDBOX_STARTING_CAPITAL": "2500000", "SCRIPT_MEMORY_LIMIT_MB": "256"}
MONTHLY = date(2026, 9, 29)
CLOSES = {
    "NIFTY 50": 24708.75,
    "NIFTY BANK": 53202.50,
    "SENSEX": 81103.71,
    "RELIANCE": 2931.50,
    "HDFCBANK": 1652.10,
    "TCS": 4139.00,
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
TCS = replace(FAKE_INSTRUMENT, symbol="TCS", broker_symbol="TCS", token="e2e-tcs")

NEAR_FUT = _derivative("NIFTY29SEP26FUT", InstrumentType.FUT, MONTHLY, None)
# The Option chain mock's NIFTY: four expiries, strikes 50 apart from 23,800
# to 25,800, priced by Black-76 off the walking NIFTY 50 (`_modelled`).
CHAIN_EXPIRIES = (MONTHLY, date(2026, 10, 6), date(2026, 10, 13), date(2026, 10, 27))
CHAIN = {
    option.symbol: option
    for expiry in CHAIN_EXPIRIES
    for strike in range(23800, 25801, 50)
    for kind in (InstrumentType.CE, InstrumentType.PE)
    for option in [
        _derivative(
            f"NIFTY{expiry.strftime('%d%b%y').upper()}{strike}{kind.value}",
            kind,
            expiry,
            float(strike),
        )
    ]
    if option.symbol not in CLOSES
}
CHAIN[NEAR_FUT.symbol] = NEAR_FUT
CARRY = 1.0004  # the futures' premium over the index

INSTRUMENTS = [
    FAKE_INSTRUMENT,
    HDFCBANK,
    TCS,
    FUT,
    CE,
    PE,
    *CHAIN.values(),
    _index("NIFTY 50", Exchange.NSE, "256265"),
    _index("NIFTY BANK", Exchange.NSE, "260105"),
    _index("SENSEX", Exchange.BSE, "265"),
]


def _modelled(instrument: Instrument) -> float:
    """A chain contract's price now: the NIFTY 50 carried to its forward, and
    for an option Black-76 at a smile that rises away from the money."""
    forward = PRICES["NIFTY 50"] * CARRY
    if instrument.instrument_type is InstrumentType.FUT or instrument.strike is None:
        return round(forward, 2)
    assert instrument.expiry is not None
    moneyness = math.log(instrument.strike / forward)
    volatility = 0.1 - 0.15 * moneyness + 1.6 * moneyness * moneyness
    years = years_to_expiry(instrument.expiry, SESSION_START)
    value = black76_price(
        instrument.instrument_type, forward, instrument.strike, years, 0.0, volatility
    )
    return max(round(round(value / 0.05) * 0.05, 2), 0.05)


def _price(instrument: Instrument) -> float:
    if instrument.symbol in PRICES:
        return PRICES[instrument.symbol]
    if instrument.symbol in CHAIN:
        return _modelled(instrument)
    return 2500.0


START_PRICES = dict(PRICES)  # where each price stood at SESSION_START
SESSION_OPEN = clock_time(9, 15)
MINUTES_PER_SESSION = 375
HISTORY_FROM = date(2025, 9, 1)
INTERVAL_MINUTES = {
    "minute": 1,
    "3minute": 3,
    "5minute": 5,
    "10minute": 10,
    "15minute": 15,
    "30minute": 30,
    "60minute": 60,
}


@functools.cache
def _minutes(symbol: str) -> tuple[tuple[datetime, float], ...]:
    """A year of minute closes on weekdays, walked back from the price at
    SESSION_START (10:30 on the Tuesday), so every interval agrees."""
    rng = random.Random(f"bars-{symbol}")
    start_local = SESSION_START.astimezone(EXCHANGE_TIMEZONE)
    stamps: list[datetime] = []
    day = HISTORY_FROM
    while day <= start_local.date():
        if day.weekday() < 5:
            opens = datetime.combine(day, SESSION_OPEN, EXCHANGE_TIMEZONE)
            for n in range(MINUTES_PER_SESSION):
                stamp = opens + timedelta(minutes=n)
                if stamp > start_local:
                    break
                stamps.append(stamp)
        day += timedelta(days=1)
    closes = [START_PRICES[symbol] if symbol in START_PRICES else _modelled(CHAIN[symbol])]
    for later, earlier in zip(reversed(stamps), list(reversed(stamps))[1:], strict=False):
        gap = 0.004 if later.date() != earlier.date() else 0.0006
        closes.append(closes[-1] * math.exp(-rng.gauss(0, gap)))
    closes.reverse()
    return tuple(zip(stamps, closes, strict=True))


@functools.cache
def _stamps(symbol: str) -> tuple[datetime, ...]:
    return tuple(stamp for stamp, _ in _minutes(symbol))


def _bars(instrument: Instrument, interval: str, start: date, end: date) -> list[Bar]:
    """Only the range's minutes are walked (found by bisection): the whole
    year each time, as the Symbol page's depth polls ask every 2 s, kept the
    server busy enough to delay live prices."""
    rng = random.Random(f"volume-{instrument.symbol}-{interval}")
    groups: dict[datetime, list[float]] = {}
    previous: dict[datetime, float] = {}
    minutes = _minutes(instrument.symbol)
    stamps = _stamps(instrument.symbol)
    lo = bisect.bisect_left(stamps, datetime.combine(start, clock_time.min, EXCHANGE_TIMEZONE))
    hi = bisect.bisect_right(stamps, datetime.combine(end, clock_time.max, EXCHANGE_TIMEZONE))
    last = minutes[lo - 1][1] if lo else None
    for stamp, close in minutes[lo:hi]:
        if interval == "day":
            key = datetime.combine(stamp.date(), clock_time(), EXCHANGE_TIMEZONE)
        else:
            every = INTERVAL_MINUTES[interval]
            since_open = (stamp.hour * 60 + stamp.minute) - (9 * 60 + 15)
            key = stamp - timedelta(minutes=since_open % every)
        if key not in groups:
            groups[key] = []
            previous[key] = last if last is not None else close
        groups[key].append(close)
        last = close
    tick = instrument.tick_size

    def snap(value: float) -> float:
        return round(round(value / tick) * tick, 2)

    return [
        Bar(
            instrument=instrument,
            interval=interval,
            open=snap(previous[key]),
            high=snap(max(previous[key], *closes)),
            low=snap(min(previous[key], *closes)),
            close=snap(closes[-1]),
            volume=rng.randint(800, 4000) * len(closes),
            timestamp=key.astimezone(UTC),
        )
        for key, closes in groups.items()
    ]


def _open_interest(instrument: Instrument) -> int | None:
    """Futures and options only: most near the money, calls more above it,
    puts more below it, in whole lots."""
    if instrument.expiry is None:
        return None
    if instrument.strike is None:
        return 1_245_600
    spot = CLOSES["NIFTY 50"]
    away = (
        (instrument.strike - spot)
        / spot
        * (1 if instrument.instrument_type is InstrumentType.CE else -1)
    )
    lots = 60_000 * math.exp(-((away * 40) ** 2)) * (1.4 if away > 0 else 0.8)
    lots += zlib.crc32(instrument.symbol.encode()) % 20_000
    return int(lots) * 75


class E2EBroker(FakeBrokerPort):
    """The fake broker quoting the walking prices, a tick either side, with
    a year of candles behind them and five levels of depth around them."""

    def get_instrument_master(self) -> list[Instrument]:
        return INSTRUMENTS

    def get_historical_bars(
        self, instrument: Instrument, interval: str, start: date, end: date
    ) -> list[Bar]:
        return _bars(instrument, interval, start, end)

    def get_market_depth(self, instrument: Instrument) -> MarketDepth:
        last = _price(instrument)
        tick = instrument.tick_size
        rng = random.Random()
        today = _bars(instrument, "day", SESSION_START.date(), SESSION_START.date())[-1]

        def level(price: float) -> DepthLevel:
            return DepthLevel(round(price, 2), rng.randint(1, 60) * 25, rng.randint(1, 50))

        return MarketDepth(
            instrument=instrument,
            as_of=datetime.now(UTC),
            last_price=last,
            last_quantity=rng.randint(1, 40),
            bids=tuple(level(last - tick * n) for n in range(1, 6)),
            asks=tuple(level(last + tick * n) for n in range(1, 6)),
            total_buy_quantity=rng.randint(10_000, 20_000),
            total_sell_quantity=rng.randint(10_000, 20_000),
            open=today.open,
            high=round(max(today.high, last), 2),
            low=round(min(today.low, last), 2),
            close=CLOSES.get(instrument.symbol),
            volume=6_124_318,
            open_interest=_open_interest(instrument),
        )

    def get_margin(self, orders: Sequence[OrderRequest]) -> MarginRequirement:
        """A sell needs 11% of what it's written on, a buy its premium; a set
        with both saves 78% of what its sells need, as a hedge."""
        spot = PRICES["NIFTY 50"]
        sells = sum(o.quantity * spot * 0.11 for o in orders if o.side is Side.SELL)
        buys = sum(o.quantity * _price(o.instrument) for o in orders if o.side is Side.BUY)
        benefit = sells * 0.78 if sells and buys else 0.0
        total = sells + buys - benefit
        return MarginRequirement(
            round(total, 2),
            round(sells * 0.8, 2),
            round(sells * 0.2, 2),
            round(buys, 2),
            round(benefit, 2),
        )

    def get_quote(self, instrument: Instrument) -> Quote:
        """A tick either side, the day's range from today's candle; an index,
        as on the exchange, has no book and no volume. A chain contract, quoted
        forty at a time, skips the candles: a year of minutes each is slow."""
        last = _price(instrument)
        index = instrument.instrument_type is InstrumentType.INDEX
        today = (
            Bar(instrument, "day", last, last, last, last, 0, SESSION_START)
            if instrument.symbol in CHAIN
            else _bars(instrument, "day", SESSION_START.date(), SESSION_START.date())[-1]
        )
        # An option's book is wider: 0.35 either side, as in the mock.
        spread = 0.35 if instrument.strike is not None else instrument.tick_size
        return Quote(
            instrument,
            last,
            datetime.now(UTC),
            open_interest=_open_interest(instrument),
            bid=None if index else max(round(last - spread, 2), 0.05),
            ask=None if index else round(last + spread, 2),
            open=today.open,
            day_high=round(max(today.high, last), 2),
            day_low=round(min(today.low, last), 2),
            close=CLOSES.get(instrument.symbol),
            volume=None
            if index
            else 1_000_000 + zlib.crc32(instrument.symbol.encode()) % 9_000_000,
        )


CLOCK_FILE = "e2e-clock"  # in the home: the wall-clock second SESSION_START stands for


class Clock:
    """Tuesday's session from SESSION_START on, at real speed. With `home`,
    every process sharing it reads one start from its clock file, so the
    server and `e2e_agent` agree on the time; moving that start back moves
    time on for all of them."""

    def __init__(self, home: Path | None = None) -> None:
        self._file = home / CLOCK_FILE if home else None
        self._started = time.time()
        if self._file is not None and not self._file.exists():
            self._file.write_text(repr(self._started))

    def __call__(self) -> datetime:
        started = float(self._file.read_text()) if self._file else self._started
        return SESSION_START + timedelta(seconds=time.time() - started)


def _stamp_events_with(clock: Clock) -> None:
    """Events stamped with the session's clock, not the wall clock, as every
    other time here is: so a chat turn's start and end, taken from the clock,
    hold the audit entries its agent made (ADR 40's What changed)."""

    class _SessionTime:  # what event types read the time from: their `_now`
        @staticmethod
        def now(tz: tzinfo) -> datetime:
            return clock().astimezone(tz)

    event_types.datetime = _SessionTime  # type: ignore[attr-defined,assignment]


class WalkingFeed:
    """A MarketFeedPort whose prices take a small random step each 300 ms,
    pulled back toward where they started: a free walk drifted NIFTY 50 a
    few hundred points over a full run, moving the chain's ATM strike that
    the Option chain spec counts on. Indices step less and are held closer
    (a few points), stocks wander a little further."""

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
            if symbol in PRICES:
                size, pull = (0.0001, 0.2) if symbol in INDICES else (0.0004, 0.05)
                step = PRICES[symbol] * self._random.uniform(-size, size) - pull * (
                    PRICES[symbol] - START_PRICES[symbol]
                )
                # On the tick, as an exchange's prices are; an index has none.
                tick = instrument.tick_size or 0.01
                PRICES[symbol] = round(round((PRICES[symbol] + step) / tick) * tick, 2)
            ticks.append(Tick(instrument, _price(instrument), self._clock()))
        return ticks

    def close(self) -> None:
        pass


def _seed(env: dict[str, str], clock: Clock) -> None:
    """The Positions mock's account (see the module docstring)."""
    sandbox = order_broker("fake", env, clock)
    events = build_event_bus({})

    def fill(
        instrument: Instrument,
        side: Side,
        quantity: int,
        product: Product,
        who: str,
        strategy_id: str | None = None,
        run_id: str | None = None,
    ) -> float:
        request = OrderRequest(
            instrument, side, quantity, product, OrderType.MARKET, None, who, strategy_id, run_id
        )
        result = place_order(request, sandbox, events, None, load_calendar(), clock())
        assert result.status is OrderStatus.FILLED and result.fill_price, result.reason
        return result.fill_price

    def run(
        name: str,
        spec: StrategySpec,
        product: Product,
        legs: Sequence[tuple[Instrument, Side, int]],
    ) -> str:
        strategy = insert_strategy(name, spec, clock())
        rules: Sequence[LegSpec | SignalLeg] = spec.legs
        run_id = runs_repo.new_run_id()
        entries = [
            fill(leg, side, units, product, f"strategy:{strategy.id}", strategy.id, run_id)
            for leg, side, units in legs
        ]
        started = Run(
            id=run_id,
            strategy_id=strategy.id,
            broker="fake",
            product=product,
            status=RunStatus.OPEN,
            trigger="schedule" if isinstance(spec, OptionsStrategySpec) else "alert",
            started_at=clock(),
            legs=tuple(
                RunLeg(
                    f"leg{n}",
                    leg.symbol,
                    leg.exchange,
                    side,
                    units,
                    LegStatus.OPEN,
                    entry_price=entry,
                    entered_at=clock(),
                    risk=leg_risk(spec_leg, side, entry, units),
                )
                for n, ((leg, side, units), entry, spec_leg) in enumerate(
                    zip(legs, entries, rules, strict=True), 1
                )
            ),
        )
        with write_transaction() as session:
            runs_repo.insert_run(session, started)
        return strategy.id

    def place(
        instrument: Instrument,
        side: Side,
        quantity: int,
        product: Product,
        order_type: OrderType,
        who: str,
        price: float | None = None,
        trigger: float | None = None,
    ) -> OrderResult:
        request = OrderRequest(
            instrument, side, quantity, product, order_type, price, who, trigger_price=trigger
        )
        return place_order(request, sandbox, events, None, load_calendar(), clock())

    straddle = run(
        "NIFTY short straddle",
        STRADDLE_E2E,
        Product.MIS,
        [(CE, Side.SELL, 75), (PE, Side.SELL, 75)],
    )
    trend = run("NIFTY futures trend", TREND, Product.NRML, [(FUT, Side.BUY, 75)])
    strategies = seed_strategies(clock, straddle, trend)
    fill(FUT, Side.BUY, 75, Product.NRML, "ui")
    fill(FAKE_INSTRUMENT, Side.BUY, 10, Product.MIS, "ui")
    fill(HDFCBANK, Side.SELL, 20, Product.MIS, "mcp:claude-code")

    # The Orders mock's book: a resting limit, a script's stop, a refusal, a cancel.
    trail = upload_script("rel_trail.py", REL_TRAIL, clock())
    place(HDFCBANK, Side.BUY, 25, Product.CNC, OrderType.LIMIT, "ui", price=1640.0)
    stop = place(
        FAKE_INSTRUMENT,
        Side.SELL,
        10,
        Product.MIS,
        OrderType.SL_M,
        f"script:{trail.id}",
        trigger=2915.0,
    )
    refused = place(FUT, Side.BUY, 7500, Product.NRML, OrderType.MARKET, "mcp:codex")
    dropped = place(FAKE_INSTRUMENT, Side.BUY, 5, Product.CNC, OrderType.LIMIT, "ui", price=2800.0)
    assert stop.status is OrderStatus.PENDING, stop.reason
    assert refused.status is OrderStatus.REJECTED
    assert dropped.broker_order_id is not None
    cancel_order(dropped.broker_order_id, sandbox, events, "ui")

    # The Trades mock's TCS round trips (see the module docstring).
    yesterday = order_broker("fake", env, lambda: clock() - timedelta(days=1))
    for broker, bought, sold in ((yesterday, 4010.0, 4031.0), (sandbox, 3970.0, 4139.0)):
        for side, at in ((Side.BUY, bought), (Side.SELL, sold)):
            PRICES["TCS"] = at
            request = OrderRequest(TCS, side, 15, Product.MIS, OrderType.MARKET, None, "ui")
            filled = place_order(request, broker, events, None, load_calendar(), clock())
            assert filled.status is OrderStatus.FILLED, filled.reason
    with write_transaction() as session:
        session.execute(
            update(SandboxTradeRow)
            .where(SandboxTradeRow.filled_at < SESSION_START.replace(tzinfo=None))
            .values(realized_pnl=None, charges_detail=None)
        )
    seed_scripts(trail.id, clock)
    seed_agents(strategies, clock)
    seed_chat(straddle, clock)
    seed_gone_chat(clock)
    seed_brain(straddle, clock, events)
    events.close()


def _seed_pnl(now: datetime) -> None:
    """The Dashboard's record (ADR 34): a point a minute from 09:15 to now,
    and a result for each weekday of the last four months."""
    today = now.astimezone(EXCHANGE_TIMEZONE).date()
    minute = datetime.combine(today, clock_time(9, 15), EXCHANGE_TIMEZONE)
    step = 0
    while minute <= now:
        swing = 2400.0 * math.sin(step / 11) + 38.0 * step - 900.0
        # Trades close through the day and pay charges; what's open makes up the rest.
        realized, charges = round(14.0 * step, 2), round(1.6 * step, 2)
        upsert_point(
            today,
            IntradayPoint(
                minute.time(),
                round(swing, 2),
                realized,
                charges,
                round(swing - realized + charges, 2),
            ),
        )
        minute += timedelta(minutes=1)
        step += 1
    rng = random.Random(8)
    for back in range(1, 121):
        day = today - timedelta(days=back)
        if day.weekday() >= 5:
            continue
        net = round(rng.gauss(900, 3800), 2)
        charges = round(abs(rng.gauss(160, 60)), 2)
        upsert_day(
            DayPnl(day, net + charges, charges, 0.0, net, 0.0, rng.randint(2, 24), True),
            now,
        )


def _seed_manager_history(now: datetime) -> None:
    """Yesterday as the manager left it (ADR 43): its thread of three looks,
    its plan, its numbers set before the open, one changed by the user, and
    the close look's for today."""
    yesterday = now.astimezone(EXCHANGE_TIMEZONE).date() - timedelta(days=1)
    first = list_strategies()[0]

    def at(hour: int, minute: int) -> datetime:
        return datetime.combine(yesterday, clock_time(hour, minute), EXCHANGE_TIMEZONE)

    with write_transaction() as session:
        thread = agent_threads_repo.add_thread(
            session, Folder.MANAGER, yesterday.isoformat(), Harness.CLAUDE, "Manager", at(9, 0)
        )
        for when, reason, model, effort, cost, said in (
            (
                at(9, 0),
                "plan",
                "claude-opus-5-5",
                "high",
                0.21,
                f"{first.name} runs with ₹2,00,000 and a -₹6,000 stop. Desk stop -₹30,000.",
            ),
            (
                at(12, 0),
                "scheduled",
                "claude-sonnet-5-5",
                "low",
                0.02,
                "Nothing changed since 09:00.",
            ),
            (
                at(15, 35),
                "close",
                "claude-opus-5-5",
                "high",
                0.05,
                "Desk up on the day. A smaller desk stop tomorrow: -₹20,000.",
            ),
        ):
            turn = agent_jobs_repo.add_job(
                session,
                AgentJobKind.CHAT,
                None,
                Harness.CLAUDE,
                f"manager-wake:{reason}",
                when,
                thread_id=thread.id,
                prompt=f'<wake reason="{reason}" day="{yesterday}">',
                model=model,
                effort=effort,
            )
            agent_jobs_repo.mark_running(session, turn.id, 4400, when)
            agent_jobs_repo.mark_outcome(
                session, turn.id, AgentOutcome(None, cost, None, model), Usage(cost, None, None)
            )
            agent_jobs_repo.end_job(
                session,
                turn.id,
                AgentJobEndReason.FINISHED,
                "exited with code 0",
                when + timedelta(seconds=40),
                0,
                said,
                cost,
            )
    record_event(
        ManagerPlanSet(
            yesterday,
            f"Run {first.name} small, with a stop under its worst run; nothing new starts.",
            (),
            f"manager:claude:{thread.id}",
            occurred_at=at(9, 3),
        )
    )

    for key, name, capital, stop, set_by, reason, when in (
        ("desk", None, None, -30000.0, "manager", "about half the strategies' stops", at(9, 2)),
        (
            f"strategy:{first.id}",
            first.name,
            200000.0,
            -6000.0,
            "manager",
            "1.8x its median losing run",
            at(9, 2),
        ),
        (f"strategy:{first.id}", first.name, 200000.0, -4000.0, "you", "set by you", at(11, 20)),
        ("desk", None, None, -20000.0, "manager", "a smaller desk tomorrow", at(15, 36)),
    ):
        record_event(
            ManagerNumbersChanged(
                key=key,
                name=name,
                capital=capital,
                stop=stop,
                set_by=set_by,
                kept_yours=False,
                reason=reason,
                triggered_by="ui" if set_by == "you" else f"manager:claude:{thread.id}",
                occurred_at=when,
            )
        )


def _seed_watchlists(now: datetime) -> None:
    """The Watchlist mock's lists (ADR 36), without RELIANCE: Claude adds it."""
    for name, symbols in (
        (
            "Core",
            [
                ("NSE", "NIFTY 50"),
                ("NSE", "HDFCBANK"),
                ("NSE", "TCS"),
                ("NFO", "NIFTY27OCT26FUT"),
                ("NFO", "NIFTY29SEP2624800CE"),
            ],
        ),
        ("Banks", [("NSE", "NIFTY BANK"), ("NSE", "HDFCBANK")]),
    ):
        made = insert_watchlist(name, now)
        add_items(made.watchlist_id, [WatchlistItem(exchange=e, symbol=s) for e, s in symbols])


def _serve_broker_login(port: int) -> str:
    """The broker's login page, on another site (`localhost`, not
    `127.0.0.1`), as Kite's is: its "Log in" goes to the app's callback, so
    the browser arrives there cross-site, cookie withheld. Its URL."""

    callback = f"http://127.0.0.1:{port}/brokers/fake/callback?request_token=e2e&status=success"
    page = (
        "<!doctype html><title>Fake broker login</title>"
        f'<h1>Log in to the fake broker</h1><a href="{callback}">Log in</a>'
    ).encode()

    class Login(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page)

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port + 1), Login)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return f"http://localhost:{port + 1}/connect/login"


def _pending_job_ids() -> set[str]:
    with Session(get_engine()) as session:
        rows = session.scalars(
            select(AgentJobRow.id).where(AgentJobRow.status == AgentJobStatus.PENDING.value)
        )
        return set(rows.all())


def _run_agents(
    home: Path, events: EventPublisher, url: str, clock: Clock, stop: threading.Event
) -> None:
    """The daemon's agent lanes (ADR 40), with tests/fixtures/fake_claude.py as
    Claude Code and fake_codex.py as Codex: every chat, the desk manager's
    wakes (ADR 41), and the reviews asked for while the suite runs.
    Jobs seeded before it started stay as they were (the Agents mock's
    waiting review stays waiting), and so do debriefs (Brain's proof stops
    one before it starts)."""
    seeded = _pending_job_ids()

    def next_pending(session: Session) -> AgentJob | None:
        row = session.scalars(
            select(AgentJobRow)
            .where(
                AgentJobRow.status == AgentJobStatus.PENDING.value,
                AgentJobRow.kind == AgentJobKind.REVIEW.value,
                AgentJobRow.id.not_in(seeded),
            )
            .order_by(AgentJobRow.created_at)
        ).first()
        return agent_jobs_repo.find_job(row.id) if row else None

    agent_jobs_repo.next_pending = next_pending
    home = home.resolve()  # the agent runs in it, so its paths can't be relative
    bin_dir = home / "bin"
    bin_dir.mkdir(exist_ok=True)
    for name in ("claude", "codex"):
        shim = bin_dir / name
        fake = Path(__file__).with_name(f"fake_{name}.py")
        shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" -I "{fake}" "$@"\n')
        shim.chmod(0o755)
    parent = {**os.environ, "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}"}
    context = AgentContext(HarnessProcesses(parent), events, AgentSettings(), home, url + MCP_PATH)

    def run() -> None:
        while not stop.is_set():
            now = clock()
            settled = replace(context, settings=resolved_settings(context.settings))
            watch_jobs(settled, now)
            queue_due_manager_wake(settled, now)
            start_next_job(settled, now)
            start_next_chat_turn(settled, now)
            stop.wait(0.25)

    threading.Thread(target=run, daemon=True, name="chats").start()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8751)
    parser.add_argument("--home", required=True)
    parser.add_argument("--links", required=True)
    args = parser.parse_args()
    os.environ["OPENTICKER_HOME"] = args.home

    registry.register("fake", E2EBroker)
    kite = _serve_broker_login(args.port)
    registry.register_login_url_builder("fake", lambda: kite)
    upsert_instruments(INSTRUMENTS)
    clock = Clock(Path(args.home))
    _stamp_events_with(clock)
    save_credentials(Credentials("fake", "e2e", None, clock() + timedelta(hours=8)))
    env = dict(E2E_ENV)
    _seed(env, clock)
    _seed_pnl(clock())
    _seed_manager_history(clock())
    _seed_watchlists(clock())

    events = build_event_bus({})
    prices = LatestPrices()
    wake = threading.Event()
    stop = threading.Event()

    def quote(instruments: Sequence[Instrument]) -> list[Quote]:
        return [
            E2EBroker().get_quote(i) for i in instruments if i.symbol in PRICES or i.symbol in CHAIN
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
    scripts = ScriptLoop(
        ProcessSupervisor(),
        events,
        load_calendar,
        script_limits(env),
        f"http://127.0.0.1:{args.port}",
        clock,
    )
    threading.Thread(target=scripts.run, args=(stop,), daemon=True).start()

    _run_agents(Path(args.home), events, f"http://127.0.0.1:{args.port}", clock, stop)
    # Settings › Agents finds the fake Claude Code where the chat lane does.
    env["PATH"] = f"{Path(args.home).resolve() / 'bin'}:{os.environ.get('PATH', '')}"

    web = WebSettings(f"http://127.0.0.1:{args.port}", args.port, None, DIST)
    # MCP at /mcp as openticker-serve serves it, on the session's clock: a
    # real agent can be put behind bin/claude and work the e2e desk.
    mcp_server.clock = clock
    app = WithMcp(create_app(events, env, clock=clock, hub=hub, web=web), mcp_server.mcp)
    links = [create_sign_in_link(web.own_origin, clock()) for _ in range(160)]
    Path(args.links).write_text("\n".join(links) + "\n")
    try:
        uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        stop.set()
        events.close()


if __name__ == "__main__":
    main()
