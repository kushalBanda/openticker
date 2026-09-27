"""When a scheduled strategy enters, and when a run must close on its
schedule. Pure. Rules: ADR 22 in docs/adr."""

from datetime import date, datetime, time, timedelta

from openticker.core.calendar.calendar import session_hours, square_off_at
from openticker.core.calendar.models import MarketCalendar
from openticker.core.risk.models import StrategyStopReason
from openticker.core.strategies.models import Schedule
from openticker.ports.models import EXCHANGE_TIMEZONE, Exchange

# A scheduled entry the daemon finds later than this is skipped for the day:
# long enough to survive a busy pass, short enough not to enter a market that
# has moved.
ENTRY_GRACE = timedelta(seconds=60)
_LOOKBACK_DAYS = 15  # longer than any run of market holidays and weekends


def entry_due(
    schedule: Schedule, exchange: Exchange, calendar: MarketCalendar, now: datetime
) -> datetime | None:
    """Today's entry time, while an entry at it may still be sent: on a
    scheduled weekday the exchange trades, from `entry_time` for ENTRY_GRACE."""
    if schedule.entry_time is None:
        return None
    today = now.astimezone(EXCHANGE_TIMEZONE).date()
    if today.weekday() not in schedule.weekdays:
        return None
    if session_hours(today, exchange, calendar) is None:
        return None
    at = datetime.combine(today, schedule.entry_time, EXCHANGE_TIMEZONE)
    return at if at <= now < at + ENTRY_GRACE else None


def next_entry(
    schedule: Schedule, exchange: Exchange, calendar: MarketCalendar, now: datetime
) -> datetime | None:
    """When the schedule enters next: today's entry while it is still due,
    else the next scheduled weekday the exchange trades."""
    if schedule.entry_time is None:
        return None
    today = now.astimezone(EXCHANGE_TIMEZONE).date()
    for ahead in range(_LOOKBACK_DAYS):
        day = today + timedelta(days=ahead)
        if day.weekday() not in schedule.weekdays:
            continue
        if session_hours(day, exchange, calendar) is None:
            continue
        at = datetime.combine(day, schedule.entry_time, EXCHANGE_TIMEZONE)
        if now < at + ENTRY_GRACE:
            return at
    return None


def exit_due(
    schedule: Schedule,
    started_at: datetime,
    expiries: set[date],
    exchange: Exchange,
    calendar: MarketCalendar,
    now: datetime,
) -> tuple[StrategyStopReason, str] | None:
    """Why a run must close now on its schedule, if it must.

    On the expiry day of any contract it holds (with `exit_on_expiry`), it
    closes at `exit_time`, or at the intraday square-off when there is none,
    rather than be settled. Otherwise `exit_time` closes it on every trading
    day, whatever its horizon, once it has been open across that time; one
    missed while the daemon was down closes it at the next session.
    """
    today = now.astimezone(EXCHANGE_TIMEZONE).date()
    hours = session_hours(today, exchange, calendar)
    if hours is None:
        return None
    if schedule.exit_on_expiry and today in expiries:
        at = (
            datetime.combine(today, schedule.exit_time, EXCHANGE_TIMEZONE)
            if schedule.exit_time is not None
            else square_off_at(hours)
        )
        if now >= at:
            local = at.astimezone(EXCHANGE_TIMEZONE)
            return StrategyStopReason.EXPIRY, f"expiry day exit {local:%H:%M}"
    if schedule.exit_time is not None:
        last = _last_exit(schedule.exit_time, exchange, calendar, now)
        if last is not None and started_at < last:
            return StrategyStopReason.SCHEDULE, f"exit_time {schedule.exit_time:%H:%M}"
    return None


def _last_exit(
    exit_time: time, exchange: Exchange, calendar: MarketCalendar, now: datetime
) -> datetime | None:
    """The latest `exit_time` at or before `now` on a day the exchange traded."""
    today = now.astimezone(EXCHANGE_TIMEZONE).date()
    for back in range(_LOOKBACK_DAYS):
        day = today - timedelta(days=back)
        at = datetime.combine(day, exit_time, EXCHANGE_TIMEZONE)
        if at <= now and session_hours(day, exchange, calendar) is not None:
            return at
    return None
