"""Market calendar shapes (ADR 13 in docs/adr)."""

from dataclasses import dataclass
from datetime import date, datetime, time

from openticker.ports.models import Exchange


@dataclass(frozen=True)
class Holiday:
    day: date
    name: str
    exchanges: frozenset[Exchange]  # closed all day, unless a special session says otherwise


@dataclass(frozen=True)
class SpecialSession:
    """Hours that replace the regular ones for one exchange on one day: Muhurat
    trading, or MCX's evening-only session on an equity holiday. A missing
    bound means the regular one."""

    day: date
    name: str
    exchange: Exchange
    opens: time | None
    closes: time | None


@dataclass(frozen=True)
class MarketCalendar:
    years: frozenset[int]  # years the holiday list covers
    holidays: tuple[Holiday, ...]
    special_sessions: tuple[SpecialSession, ...]


@dataclass(frozen=True)
class SessionHours:
    exchange: Exchange
    day: date
    opens_at: datetime  # tz-aware, exchange-local
    closes_at: datetime
    name: str | None  # set for a special session


@dataclass(frozen=True)
class MarketStatus:
    exchange: Exchange
    is_open: bool
    session: SessionHours  # the one in progress, else the next one
    closed_reason: str | None  # why it is closed now: weekend, a holiday's name, ...
    holidays_known: bool  # False when the calendar doesn't cover this year
