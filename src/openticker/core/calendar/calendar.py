"""Trading days and session hours per exchange. Pure: the calendar is passed
in (ADR 13 in docs/adr).

Regular hours: NSE, BSE and their derivatives 09:15-15:30. MCX 09:00 to 23:30,
or 23:55 while the US is on standard time, because MCX follows the hours of
the US markets its contracts track.
"""

from collections.abc import Mapping
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from openticker.core.calendar.models import (
    Holiday,
    MarketCalendar,
    MarketStatus,
    SessionHours,
    SpecialSession,
)
from openticker.ports.models import EXCHANGE_TIMEZONE, Exchange

EQUITY_HOURS = (time(9, 15), time(15, 30))
_MCX_OPEN = time(9, 0)
_MCX_CLOSE_US_SUMMER = time(23, 30)
_MCX_CLOSE_US_WINTER = time(23, 55)
_NEW_YORK = ZoneInfo("America/New_York")
_LOOKAHEAD_DAYS = 31
SQUARE_OFF_BEFORE_CLOSE = timedelta(minutes=15)


class CalendarError(Exception):
    pass


def regular_hours(day: date, exchange: Exchange) -> tuple[time, time]:
    if exchange is not Exchange.MCX:
        return EQUITY_HOURS
    noon_in_new_york = datetime.combine(day, time(12), _NEW_YORK)
    us_summer = bool(noon_in_new_york.dst())
    return _MCX_OPEN, _MCX_CLOSE_US_SUMMER if us_summer else _MCX_CLOSE_US_WINTER


def session_hours(day: date, exchange: Exchange, calendar: MarketCalendar) -> SessionHours | None:
    """None when the exchange doesn't trade that day."""
    opens, closes = regular_hours(day, exchange)
    for special in calendar.special_sessions:
        if special.day == day and special.exchange is exchange:
            return _hours(
                exchange, day, special.opens or opens, special.closes or closes, special.name
            )
    if day.weekday() >= 5 or holiday_on(day, exchange, calendar) is not None:
        return None
    return _hours(exchange, day, opens, closes, None)


def holiday_on(day: date, exchange: Exchange, calendar: MarketCalendar) -> Holiday | None:
    return next((h for h in calendar.holidays if h.day == day and exchange in h.exchanges), None)


def next_session(after: datetime, exchange: Exchange, calendar: MarketCalendar) -> SessionHours:
    """The session in progress at `after`, or the next one to open."""
    day = after.astimezone(EXCHANGE_TIMEZONE).date()
    for offset in range(_LOOKAHEAD_DAYS):
        hours = session_hours(day + timedelta(days=offset), exchange, calendar)
        if hours is not None and hours.closes_at > after:
            return hours
    raise CalendarError(f"no {exchange} session in the {_LOOKAHEAD_DAYS} days after {after}")


def square_off_at(hours: SessionHours) -> datetime:
    """When intraday (MIS) positions are closed: 15 minutes before the close,
    as brokers do, so they exit while the market is still liquid."""
    return hours.closes_at - SQUARE_OFF_BEFORE_CLOSE


def intraday_allowed(now: datetime, exchange: Exchange, calendar: MarketCalendar) -> bool:
    """Whether an MIS position may be open now: inside today's session and
    before its square-off. At any other time one left open is overdue."""
    hours = session_hours(now.astimezone(EXCHANGE_TIMEZONE).date(), exchange, calendar)
    return hours is not None and hours.opens_at <= now < square_off_at(hours)


def market_status(now: datetime, exchange: Exchange, calendar: MarketCalendar) -> MarketStatus:
    today = now.astimezone(EXCHANGE_TIMEZONE).date()
    hours = session_hours(today, exchange, calendar)
    is_open = hours is not None and hours.opens_at <= now < hours.closes_at
    if is_open:
        reason = None
    elif hours is not None:
        reason = "before the session" if now < hours.opens_at else "after the session"
    elif (holiday := holiday_on(today, exchange, calendar)) is not None:
        reason = holiday.name
    else:
        reason = "weekend"
    return MarketStatus(
        exchange=exchange,
        is_open=is_open,
        session=next_session(now, exchange, calendar),
        closed_reason=reason,
        holidays_known=today.year in calendar.years,
    )


def parse_calendar(data: Mapping[str, Any]) -> MarketCalendar:
    """From the holiday file's JSON. Raises CalendarError naming the bad entry."""
    try:
        return MarketCalendar(
            years=frozenset(int(year) for year in data["years"]),
            holidays=tuple(
                Holiday(
                    day=date.fromisoformat(entry["date"]),
                    name=entry["name"],
                    exchanges=frozenset(Exchange(name) for name in entry["exchanges"]),
                )
                for entry in data["holidays"]
            ),
            special_sessions=tuple(
                SpecialSession(
                    day=date.fromisoformat(entry["date"]),
                    name=entry["name"],
                    exchange=Exchange(entry["exchange"]),
                    opens=time.fromisoformat(entry["opens"]) if "opens" in entry else None,
                    closes=time.fromisoformat(entry["closes"]) if "closes" in entry else None,
                )
                for entry in data.get("special_sessions", [])
            ),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CalendarError(f"holiday file is malformed: {exc!r}") from exc


def _hours(
    exchange: Exchange, day: date, opens: time, closes: time, name: str | None
) -> SessionHours:
    return SessionHours(
        exchange=exchange,
        day=day,
        opens_at=datetime.combine(day, opens, EXCHANGE_TIMEZONE),
        closes_at=datetime.combine(day, closes, EXCHANGE_TIMEZONE),
        name=name,
    )
