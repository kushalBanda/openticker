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
    quantity: int
    average_price: float
    last_price: float


@dataclass(frozen=True)
class Funds:
    broker: str
    available_cash: float
    used_margin: float
