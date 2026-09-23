"""When a scheduled script should be running, and when its run must stop.
Pure. Rules: ADR 25 in docs/adr."""

from datetime import datetime, timedelta

from openticker.core.calendar.calendar import session_hours
from openticker.core.calendar.models import MarketCalendar
from openticker.core.scripts.models import ScriptSchedule
from openticker.ports.models import EXCHANGE_TIMEZONE


def in_window(schedule: ScriptSchedule, calendar: MarketCalendar, now: datetime) -> bool:
    """From `start_time` until `stop_time` (or midnight), on a scheduled
    weekday its exchange trades."""
    local = now.astimezone(EXCHANGE_TIMEZONE)
    today = local.date()
    if today.weekday() not in schedule.weekdays:
        return False
    if session_hours(today, schedule.exchange, calendar) is None:
        return False
    if local.time() < schedule.start_time:
        return False
    return schedule.stop_time is None or local.time() < schedule.stop_time


def stop_due(schedule: ScriptSchedule, started_at: datetime, now: datetime) -> datetime | None:
    """The `stop_time` a run started at `started_at` has run past, if any:
    every day, whether it was started by hand or by the schedule."""
    if schedule.stop_time is None:
        return None
    today = now.astimezone(EXCHANGE_TIMEZONE).date()
    at = datetime.combine(today, schedule.stop_time, EXCHANGE_TIMEZONE)
    if at > now:
        at -= timedelta(days=1)
    return at if started_at < at else None
