"""Shared DTOs every port speaks. Framework-free: dataclasses and stdlib only."""

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from zoneinfo import ZoneInfo


class Exchange(StrEnum):
    NSE = "NSE"
    BSE = "BSE"
    NFO = "NFO"
    BFO = "BFO"
    MCX = "MCX"


# Every `Exchange` member is an Indian exchange; trading dates and session
# times are on this clock (ADR 3 in docs/adr).
EXCHANGE_TIMEZONE = ZoneInfo("Asia/Kolkata")


class Interval(StrEnum):
    """Candle intervals, broker-independent. Adapters map these to their own."""

    MINUTE = "minute"
    MINUTE_3 = "3minute"
    MINUTE_5 = "5minute"
    MINUTE_10 = "10minute"
    MINUTE_15 = "15minute"
    MINUTE_30 = "30minute"
    MINUTE_60 = "60minute"
    DAY = "day"


class InstrumentType(StrEnum):
    EQ = "EQ"
    FUT = "FUT"
    CE = "CE"
    PE = "PE"
    INDEX = "INDEX"  # not tradeable; quoted as an options underlying (ADR 4 in docs/adr)


class Side(StrEnum):
    """Order/position direction."""

    BUY = "BUY"
    SELL = "SELL"


class Product(StrEnum):
    """What a position is for, which decides its margin and whether it is
    squared off at the session close."""

    MIS = "MIS"  # intraday
    NRML = "NRML"  # futures and options carried overnight
    CNC = "CNC"  # equity delivery


@dataclass(frozen=True)
class Instrument:
    symbol: str
    broker_symbol: str
    exchange: Exchange
    broker_exchange: str
    token: str
    expiry: date | None
    strike: float | None
    lot_size: int
    instrument_type: InstrumentType
    tick_size: float


@dataclass(frozen=True)
class Quote:
    instrument: Instrument
    last_price: float
    as_of: datetime  # tz-aware (UTC) — callers populate this, never naive local time
    open_interest: int | None = None  # derivatives only
    day_high: float | None = None
    day_low: float | None = None
    # A full broker quote carries these; feed ticks and polled prices may not.
    bid: float | None = None  # best buy price waiting
    ask: float | None = None  # best sell price waiting
    bid_quantity: int | None = None  # waiting at the best bid
    ask_quantity: int | None = None
    open: float | None = None
    close: float | None = None  # the previous session's
    volume: int | None = None


@dataclass(frozen=True)
class DepthLevel:
    price: float
    quantity: int
    orders: int


@dataclass(frozen=True)
class MarketDepth:
    """The order book's best levels for one instrument, with the day so far."""

    instrument: Instrument
    as_of: datetime  # tz-aware UTC
    last_price: float
    last_quantity: int | None
    bids: tuple[DepthLevel, ...]  # best first, up to 5; empty levels left out
    asks: tuple[DepthLevel, ...]
    total_buy_quantity: int  # the whole book, not only the levels shown
    total_sell_quantity: int
    open: float | None
    high: float | None
    low: float | None
    close: float | None  # the previous session's
    volume: int | None
    open_interest: int | None


@dataclass(frozen=True)
class Bar:
    instrument: Instrument
    interval: str  # "day", "minute", ...
    open: float
    high: float
    low: float
    close: float
    volume: int
    timestamp: datetime  # tz-aware (UTC), same rule as Quote.as_of


@dataclass(frozen=True)
class Credentials:
    broker: str
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None


@dataclass(frozen=True)
class Position:
    instrument: Instrument
    product: Product
    quantity: int  # net and signed, as brokers report it: negative is short
    average_price: float  # of the open quantity; 0 when flat
    last_price: float | None  # None when no current price could be fetched
    realized_pnl: float
    unrealized_pnl: float | None


@dataclass(frozen=True)
class MarginRequirement:
    """What the broker would block for a set of orders, as it would place
    them now. For several orders, with the hedge benefit they give each other
    and the account's open positions taken into account."""

    total: float
    span: float
    exposure: float
    option_premium: float
    benefit: float  # the broker's own hedge benefit for the set; 0 for one order


@dataclass(frozen=True)
class Funds:
    broker: str
    available_cash: float
    used_margin: float
    total_capital: float
    realized_pnl: float


@dataclass(frozen=True)
class Tick:
    """One streamed price (ADR 13 in docs/adr)."""

    instrument: Instrument
    last_price: float
    received_at: datetime  # tz-aware UTC, our clock: an LTP tick carries no time of its own
