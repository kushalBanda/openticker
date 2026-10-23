"""When a scheduled script should be running, and when its run must stop.
Pure. Rules: ADR 25 in docs/adr."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from openticker.core.calendar.calendar import session_hours
from openticker.core.calendar.models import MarketCalendar
from openticker.core.scripts.models import (
    ENDED_BY_ABSENCE,
    ScriptRun,
    ScriptSchedule,
    ScriptStopReason,
)
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


MAX_CRASH_RESTARTS = 3  # a scheduled script that keeps crashing is left for the day
CRASH_BACKOFF = timedelta(minutes=1)  # doubled after each crash
AT_ONCE = datetime.min.replace(tzinfo=UTC)


def next_scheduled_start(runs: Sequence[ScriptRun]) -> datetime | None:
    """When the schedule may start the script again, given its runs since
    today's start_time; None when the day's run is over (ADR 25, 46).

    A run openticker-serve's absence ended doesn't count. One that ended by
    itself, was stopped, hit its stop_time or a limit, or couldn't start is
    the day's run. A crash (`failed`) is started again after CRASH_BACKOFF,
    doubled each time, until MAX_CRASH_RESTARTS restarts are used up: one
    timeout shouldn't end a scheduled script's day."""
    counted = [run for run in runs if run.stop_reason not in ENDED_BY_ABSENCE]
    if not counted:
        return AT_ONCE
    if any(run.stop_reason is not ScriptStopReason.FAILED for run in counted):
        return None  # still running, or its day's run ended
    if len(counted) > MAX_CRASH_RESTARTS:
        return None
    last = max(run.ended_at or run.started_at for run in counted)
    return last + CRASH_BACKOFF * (1 << (len(counted) - 1))
