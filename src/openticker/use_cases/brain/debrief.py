"""The daily debrief as a job (ADR 29's agent jobs, for a trading day): asking
for one, setting when it runs on its own after the close, and the
server's own note on a day with nothing to debrief."""

from datetime import date, datetime, time, timedelta

from openticker.core.agents.debriefs import (
    DayActivity,
    DebriefOutcome,
    DebriefSchedule,
    debrief_due,
)
from openticker.core.agents.jobs import (
    SCHEDULE_TRIGGER,
    AgentJob,
    AgentJobKind,
    AgentSettings,
)
from openticker.core.brain.notes import NoteKind, WrittenBy, day_title
from openticker.core.calendar.calendar import session_hours
from openticker.core.calendar.models import MarketCalendar
from openticker.core.risk.models import StrategyStopReason
from openticker.events.bus import EventPublisher
from openticker.events.types import DebriefWritten
from openticker.ports.models import EXCHANGE_TIMEZONE, Exchange
from openticker.storage.calendar_file import load_calendar
from openticker.storage.sqlite import agent_jobs_repo, brain_repo, pnl_repo, runs_repo
from openticker.storage.sqlite.strategies_repo import write_transaction
from openticker.use_cases.agents.manage import AgentJobBusyError, AgentJobCapError
from openticker.use_cases.brain.read import check_trading_day, owed_on
from openticker.use_cases.pnl_history import day_window

DEBRIEF_TRIGGER = SCHEDULE_TRIGGER + "after the close"
QUIET_HEADLINE = "A quiet day: no fills, no runs ended, no lesson owed a check."


def debrief_outcome(
    now: datetime, calendar: MarketCalendar | None = None
) -> tuple[DebriefOutcome, date]:
    """Whether today's debrief is due now, and today's date."""
    calendar = calendar or load_calendar()
    at = brain_repo.get_debrief_at()
    today = now.astimezone(EXCHANGE_TIMEZONE).date()
    trading = session_hours(today, Exchange.NSE, calendar) is not None
    if at is None or not trading:
        return DebriefOutcome.NOTHING, today
    return debrief_due(DebriefSchedule(at), now, trading, day_activity(today)), today


def day_activity(trading_date: date) -> DayActivity:
    start, end = day_window(trading_date)
    ended = [
        r for r in runs_repo.runs_of_day((), start, end) if r.ended_at and start <= r.ended_at < end
    ]
    note = brain_repo.find_note(NoteKind.DAY, trading_date.isoformat())
    with brain_repo.reading() as session:
        job = agent_jobs_repo.debrief_for(session, trading_date)
    return DayActivity(
        pnl_recorded=bool(pnl_repo.days_between(trading_date, trading_date)),
        fills=len(pnl_repo.fills_between(start, end)),
        runs_ended=len(ended),
        kills=sum(1 for r in ended if r.stop_reason is StrategyStopReason.KILL),
        checks_owed=len(owed_on(trading_date)),
        debrief_exists=job is not None or (note is not None and "headline" in note.data),
    )


def write_quiet_day(trading_date: date, events: EventPublisher, now: datetime) -> None:
    """The server's one line for a day with nothing to debrief: no job runs."""
    with write_transaction() as session:
        note = brain_repo.write_note(
            session,
            None,
            NoteKind.DAY,
            trading_date.isoformat(),
            title=day_title(trading_date),
            body="",
            data={"headline": QUIET_HEADLINE, "trade_notes": [], "hindsight": [], "quiet": True},
            state=None,
            strategy_id=None,
            structural=(),
            written_by=WrittenBy.SERVER,
            now=now,
            by=brain_repo.SERVER,
            keep=("frozen", "frozen_at"),
        )
    events.publish(
        DebriefWritten(
            trading_date=trading_date,
            note_id=note.note_id,
            headline=QUIET_HEADLINE,
            triggered_by=brain_repo.SERVER,
            quiet=True,
            occurred_at=now,
        )
    )


def latest_closed_day(now: datetime, calendar: MarketCalendar) -> date:
    """Today once its session has closed, else the last trading day before."""
    day = now.astimezone(EXCHANGE_TIMEZONE).date()
    hours = session_hours(day, Exchange.NSE, calendar)
    if hours is not None and now >= hours.closes_at:
        return day
    for _ in range(31):
        day -= timedelta(days=1)
        if session_hours(day, Exchange.NSE, calendar) is not None:
            return day
    return day


def start_debrief(
    trading_date: date | None,
    settings: AgentSettings,
    triggered_by: str,
    now: datetime,
    calendar: MarketCalendar,
) -> AgentJob:
    """A pending debrief job for openticker-serve to run; by default of the
    latest trading day that has closed. Writing it again replaces the
    day's debrief; the user's note is kept. Refused while one for that day
    waits or runs, or past the day's cap."""
    day = trading_date or latest_closed_day(now, calendar)
    check_trading_day(day, now, calendar)
    with write_transaction() as session:
        job = agent_jobs_repo.debrief_for(session, day)
        if job is not None and job.ended_at is None:
            raise AgentJobBusyError(
                f"a debrief of {day} is already {job.status} (job {job.id}); "
                "get_agent_jobs shows it"
            )
        midnight = now.astimezone(EXCHANGE_TIMEZONE).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        if agent_jobs_repo.started_since(session, midnight) >= settings.jobs_per_day:
            raise AgentJobCapError(
                f"{settings.jobs_per_day} agent jobs have run today, the daily cap "
                "(OPENTICKER_AGENT_JOBS_PER_DAY); try again tomorrow"
            )
        return agent_jobs_repo.add_job(
            session, AgentJobKind.DEBRIEF, None, settings.harness, triggered_by, now, subject=day
        )


def get_debrief_schedule(
    now: datetime, calendar: MarketCalendar
) -> tuple[time | None, datetime | None]:
    """When the debrief runs on its own, and when it's next due; (None, None): off."""
    at = brain_repo.get_debrief_at()
    if at is None:
        return None, None
    day = now.astimezone(EXCHANGE_TIMEZONE).date()
    for _ in range(31):
        if session_hours(day, Exchange.NSE, calendar) is not None:
            due = datetime.combine(day, at, EXCHANGE_TIMEZONE)
            if due > now:
                return at, due
        day += timedelta(days=1)
    return at, None


def schedule_debrief(
    at: DebriefSchedule | None, now: datetime, calendar: MarketCalendar
) -> tuple[time | None, datetime | None]:
    """Has openticker-serve debrief each trading day at `at` (15:40 or later),
    or never when None."""
    with write_transaction() as session:
        brain_repo.set_debrief_at(session, at.at if at else None)
    return get_debrief_schedule(now, calendar)
