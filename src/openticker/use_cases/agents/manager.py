"""The desk manager (ADR 41 in docs/adr): one agent, one chat thread a
trading day, that runs the paper desk. The daemon's side wakes it: each
wake is a turn of the day's thread, which the chat lane runs like any
other (use_cases/agents/supervise.py). The tools' side lets it read the
desk's lines and set them, its plan and its next look; the user's side
turns it on or off and overrides its numbers."""

import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta

from sqlalchemy.orm import Session

from openticker.core.agents.choices import look_kind, run_choice
from openticker.core.agents.jobs import (
    AgentJob,
    AgentJobEndReason,
    AgentJobKind,
    AgentJobStatus,
    AgentSettings,
)
from openticker.core.agents.manager import (
    BROKE_EVENTS,
    MAX_LINES_PER_CALL,
    MAX_REASON_CHARS,
    MAX_WAKES_PER_DAY,
    Broke,
    CloseNote,
    Crossed,
    DayUse,
    DigestLine,
    LineAtClose,
    LineChangeAt,
    LineKey,
    LineKind,
    ManagerError,
    ManagerLine,
    ManagerPlan,
    ManagerState,
    SetBy,
    Stalled,
    WakeInputs,
    WakeOutcome,
    WakeReason,
    broke,
    check_line,
    check_next_wake,
    check_plan,
    crossed_lines,
    day_use,
    digest,
    is_wake,
    lines_at,
    parse_key,
    retry_gap,
    retry_message,
    stalled,
    trailing_failures,
    wake_due,
    wake_message,
    wake_reason,
    wake_trigger,
)
from openticker.core.agents.threads import AgentThread, Folder
from openticker.core.brain.notes import NoteKind
from openticker.core.calendar.calendar import last_session, session_hours
from openticker.core.calendar.models import MarketCalendar
from openticker.core.pnl import DayFigure, Source, source_of
from openticker.core.strategies.ledger import day_figure
from openticker.events.bus import EventPublisher
from openticker.events.types import (
    ManagerNumbersChanged,
    ManagerPlanSet,
    ManagerStalled,
    ManagerSwitched,
    ManagerWoke,
)
from openticker.ports.models import EXCHANGE_TIMEZONE, Exchange
from openticker.storage.calendar_file import load_calendar
from openticker.storage.sqlite import (
    agent_jobs_repo,
    agent_threads_repo,
    brain_repo,
    manager_repo,
    pnl_repo,
)
from openticker.storage.sqlite.audit_repo import AuditEntry, list_audit
from openticker.storage.sqlite.sandbox_repo import read_funds
from openticker.storage.sqlite.scripts_repo import find_script
from openticker.storage.sqlite.strategies_repo import find_strategy, write_transaction
from openticker.use_cases.agents.manage import AgentJobBusyError, AgentJobCapError
from openticker.use_cases.agents.supervise import AgentContext
from openticker.use_cases.brain.read import UnknownNoteError
from openticker.use_cases.pnl_history import trading_day
from openticker.use_cases.strategies.board import strategy_board
from openticker.use_cases.strategies.ledger import every_ledger

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LineView:
    line: ManagerLine
    name: str | None  # the strategy's or script's; None when deleted, or for desk and own
    today: DayFigure | None  # None: no figure for it (scripts, its own trades)
    crossed: bool


class UnknownLineError(LookupError):
    """A strategy or script that doesn't exist, or no line of the user's to hand back."""


@dataclass(frozen=True)
class LineChange:
    key: str
    capital: float | None
    stop: float | None
    reason: str = ""


@dataclass(frozen=True)
class KeptYours:
    """A line the user set, which the manager wanted otherwise: the user's stands."""

    key: str
    capital: float | None
    stop: float | None
    wanted_capital: float | None
    wanted_stop: float | None


@dataclass(frozen=True)
class ManagerView:
    state: ManagerState
    thread_id: str | None  # today's
    wakes_today: int
    failures: int  # its last turns today that failed in a row
    lines: list[LineView]
    account: float  # the paper account's capital
    given: float  # capital given to strategies, scripts and its own trades
    desk_today: DayFigure | None  # the latest recorded minute's; None before the first


def get_manager(starting_capital: float, calendar: MarketCalendar, now: datetime) -> ManagerView:
    state = manager_repo.get_state()
    figures = today_figures(calendar, now)
    views = _line_views(manager_repo.lines(), figures)
    today = _day(now.astimezone(EXCHANGE_TIMEZONE).date())
    return ManagerView(
        state=state,
        thread_id=today.thread.id if today.thread else None,
        wakes_today=today.wakes,
        failures=today.failures,
        lines=views,
        account=read_funds(starting_capital).total_capital,
        given=round(
            sum(v.line.capital or 0.0 for v in views if v.line.key.kind is not LineKind.DESK), 2
        ),
        desk_today=figures.get(LineKind.DESK.value),
    )


# --- its days, read back (ADR 43) ---

MAX_DAYS = 60  # calendar days a list of its days may span


class ManagerDayError(LookupError):
    """Not a trading day, or a day still to come."""


@dataclass(frozen=True)
class ManagerDay:
    """One trading day of the manager's, read back from what was kept."""

    trading_date: date
    live: bool  # today: still moving
    ran: bool  # a thread of its exists for the day
    thread_ids: list[str]  # oldest first
    desk: DayFigure | None  # the day's record, else its last minute; None: neither kept
    use: DayUse
    lines: list["ManagerDayLine"]  # as they stood at the close
    close: datetime  # the session's close: changes after it are for the next day
    plan: ManagerPlan | None  # the newest it set for the day
    debrief: bool  # the brain's note of the day has one


@dataclass(frozen=True)
class ManagerDayLine:
    line: LineAtClose
    figure: DayFigure | None  # the strategy's that day, the desk's; None for scripts, its own
    crossed: bool  # the figure at or below the stop at the close


@dataclass(frozen=True)
class ManagerDaySummary:
    trading_date: date
    ran: bool
    net: float | None  # the desk's, after charges
    looks: int
    cost_usd: float


def get_manager_day(day: date, calendar: MarketCalendar, now: datetime) -> ManagerDay:
    today = now.astimezone(EXCHANGE_TIMEZONE).date()
    _check_day(day, today, calendar)
    found = _day(day)
    hours = session_hours(day, Exchange.NSE, calendar)
    assert hours is not None  # _check_day
    desk = _desk_figures(day, day).get(day)
    return ManagerDay(
        trading_date=day,
        live=day == today,
        ran=bool(found.threads),
        thread_ids=[thread.id for thread in found.threads],
        desk=desk,
        use=day_use(found.turns),
        lines=_lines_on(day, hours.closes_at, desk),
        close=hours.closes_at,
        plan=_plan_of(day),
        debrief=_debriefed(day),
    )


def _plan_of(day: date) -> ManagerPlan | None:
    """The newest plan it set for the day, from the audit log: the state
    keeps only the latest day's."""
    start = datetime.combine(day, time(0), EXCHANGE_TIMEZONE)
    for entry in list_audit(
        MAX_SCANNED,
        ManagerPlanSet.__name__,
        since=start,
        until=start + timedelta(days=1),
    ):  # newest first
        payload = _payload(entry)
        lessons = payload.get("lesson_ids")
        if payload.get("trading_date") == day.isoformat():
            return ManagerPlan(
                day,
                str(payload.get("text", "")),
                tuple(str(i) for i in lessons) if isinstance(lessons, list) else (),
                entry.occurred_at,
            )
    return None


def _debriefed(day: date) -> bool:
    note = brain_repo.find_note(NoteKind.DAY, day.isoformat())
    return note is not None and "headline" in note.data


MAX_CHANGES_READ = 10_000  # line changes folded for a past day's close


def _lines_on(day: date, close: datetime, desk: DayFigure | None) -> list[ManagerDayLine]:
    """The lines at the day's close, folded from the audit log, each with
    that day's figure: a strategy's from its fills, the desk's."""
    start = datetime.combine(day, time(0), EXCHANGE_TIMEZONE)
    entries = list_audit(
        MAX_CHANGES_READ,
        ManagerNumbersChanged.__name__,
        until=start + timedelta(days=1),
        oldest_first=True,
    )
    if len(entries) == MAX_CHANGES_READ:
        log.warning("read the first %d line changes only for %s", MAX_CHANGES_READ, day)
    changes = [change for entry in entries if (change := _change(entry)) is not None]
    folded = lines_at(changes, start, close)
    ledgers = every_ledger() if any(l.key.kind is LineKind.STRATEGY for l in folded) else {}
    lines = []
    for line in folded:
        figure: DayFigure | None = None
        if line.key.kind is LineKind.DESK:
            figure = desk
        elif line.key.kind is LineKind.STRATEGY and line.key.id is not None:
            figure = day_figure(ledgers.get(line.key.id, []), day)
        crossed = line.stop is not None and figure is not None and figure.net <= line.stop
        lines.append(ManagerDayLine(line, figure, line.stood and crossed))
    return lines


def _change(entry: AuditEntry) -> LineChangeAt | None:
    """None for an entry whose line can't be read: it is left out, not fatal."""
    payload = _payload(entry)
    try:
        key = parse_key(str(payload.get("key", "")))
    except ManagerError:
        return None
    capital, stop, name = payload.get("capital"), payload.get("stop"), payload.get("name")
    return LineChangeAt(
        key=key,
        name=name if isinstance(name, str) else None,
        capital=float(capital) if isinstance(capital, int | float) else None,
        stop=float(stop) if isinstance(stop, int | float) else None,
        set_by=SetBy.YOU if payload.get("set_by") == SetBy.YOU.value else SetBy.MANAGER,
        kept_yours=bool(payload.get("kept_yours", False)),
        reason=str(payload.get("reason", "")),
        at=entry.occurred_at,
    )


def list_manager_days(
    start: date, end: date, calendar: MarketCalendar, now: datetime
) -> list[ManagerDaySummary]:
    """Every trading day from `start` to `end`, oldest first; an end after
    today is cut to today."""
    end = min(end, now.astimezone(EXCHANGE_TIMEZONE).date())
    if start > end:
        raise ManagerError(f"{start} is after {end}")
    if (end - start).days >= MAX_DAYS:
        raise ManagerError(f"at most {MAX_DAYS} days at once")
    turns = agent_jobs_repo.manager_turns_between(start, end)
    desk = _desk_figures(start, end)
    summaries = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        if session_hours(day, Exchange.NSE, calendar) is None:
            continue
        use = day_use(turns.get(day, []))
        figure = desk.get(day)
        summaries.append(
            ManagerDaySummary(
                trading_date=day,
                ran=day in turns,
                net=figure.net if figure else None,
                looks=use.looks,
                cost_usd=use.cost_usd,
            )
        )
    return summaries


def _desk_figures(start: date, end: date) -> dict[date, DayFigure]:
    """The desk's money each day, market apart from charges: the record
    written after its close, else the last minute recorded (today, or a day
    whose close wasn't recorded; minutes are kept 30 days)."""
    figures = {
        day.trading_date: DayFigure(day.realized_pnl, day.charges, day.unrealized_pnl)
        for day in pnl_repo.days_between(start, end)
    }
    for day, point in pnl_repo.last_points_between(start, end).items():
        figures.setdefault(day, DayFigure.of(point))
    return figures


def _check_day(day: date, today: date, calendar: MarketCalendar) -> None:
    if day > today:
        raise ManagerDayError(f"{day} hasn't happened yet")
    if session_hours(day, Exchange.NSE, calendar) is None:
        raise ManagerDayError(f"{day} wasn't a trading day")


def set_manager_numbers(
    changes: Sequence[LineChange],
    events: EventPublisher,
    triggered_by: str,
    calendar: MarketCalendar,
    now: datetime,
) -> tuple[list[LineView], list[KeptYours]]:
    """Sets lines' capital and stop, both at once. Set by the manager (its
    calls record as "manager:…"), a line the user set keeps the user's
    numbers: the manager's are kept beside them and returned as KeptYours.
    Set by anyone else, it is the user's, and stands until handed back."""
    if not changes:
        raise ManagerError("give at least one line")
    if len(changes) > MAX_LINES_PER_CALL:
        raise ManagerError(f"at most {MAX_LINES_PER_CALL} lines at once")
    by_manager = source_of(triggered_by) is Source.MANAGER
    keys = [parse_key(change.key) for change in changes]
    if len(set(keys)) != len(keys):
        raise ManagerError("each line once per call")
    for key, change in zip(keys, changes, strict=True):
        check_line(change.capital, change.stop, change.reason, by_manager)
        _check_exists(key)
    kept: list[KeptYours] = []
    published: list[ManagerNumbersChanged] = []
    with write_transaction() as session:
        for key, change in zip(keys, changes, strict=True):
            current = manager_repo.find_line(session, key)
            reason = change.reason.strip()
            if by_manager and current is not None and current.set_by is SetBy.YOU:
                line = replace(current, manager_capital=change.capital, manager_stop=change.stop)
                kept.append(
                    KeptYours(str(key), current.capital, current.stop, change.capital, change.stop)
                )
            elif by_manager:
                line = ManagerLine(
                    key,
                    change.capital,
                    change.stop,
                    reason,
                    SetBy.MANAGER,
                    None,
                    None,
                    now,
                    triggered_by,
                )
            else:
                wanted = _managers_numbers(current)
                line = ManagerLine(
                    key,
                    change.capital,
                    change.stop,
                    reason or "set by you",
                    SetBy.YOU,
                    wanted[0],
                    wanted[1],
                    now,
                    triggered_by,
                )
            manager_repo.put_line(session, line)
            published.append(
                ManagerNumbersChanged(
                    key=str(key),
                    name=_name(line),
                    capital=change.capital,
                    stop=change.stop,
                    set_by=SetBy.MANAGER.value if by_manager else SetBy.YOU.value,
                    kept_yours=line.set_by is SetBy.YOU and by_manager,
                    reason=reason,
                    triggered_by=triggered_by,
                )
            )
    for event in published:
        events.publish(event)
    wanted_keys = {str(key) for key in keys}
    views = [v for v in _views(calendar, now) if str(v.line.key) in wanted_keys]
    return views, kept


def clear_override(
    key: str, events: EventPublisher, triggered_by: str, calendar: MarketCalendar, now: datetime
) -> LineView:
    """Hands a line the user set back to the manager: its numbers become
    what the manager last wanted (none, if it never set them)."""
    parsed = parse_key(key)
    with write_transaction() as session:
        current = manager_repo.find_line(session, parsed)
        if current is None or current.set_by is not SetBy.YOU:
            raise UnknownLineError(f"{key} has no numbers of yours to hand back")
        line = ManagerLine(
            parsed,
            current.manager_capital,
            current.manager_stop,
            "handed back to the manager",
            SetBy.MANAGER,
            None,
            None,
            now,
            triggered_by,
        )
        manager_repo.put_line(session, line)
    events.publish(
        ManagerNumbersChanged(
            key=str(parsed),
            name=_name(line),
            capital=line.capital,
            stop=line.stop,
            set_by=SetBy.MANAGER.value,
            kept_yours=False,
            reason=line.reason,
            triggered_by=triggered_by,
        )
    )
    return next(v for v in _views(calendar, now) if v.line.key == parsed)


def _managers_numbers(current: ManagerLine | None) -> tuple[float | None, float | None]:
    """What the manager wanted for a line the user is now setting."""
    if current is None:
        return None, None
    if current.set_by is SetBy.YOU:
        return current.manager_capital, current.manager_stop
    return current.capital, current.stop


def _check_exists(key: LineKey) -> None:
    if key.id is None:
        return
    if key.kind is LineKind.STRATEGY and find_strategy(key.id) is None:
        raise UnknownLineError(f"no strategy {key.id}")
    if key.kind is LineKind.SCRIPT and find_script(key.id) is None:
        raise UnknownLineError(f"no script {key.id}")


def _views(calendar: MarketCalendar, now: datetime) -> list[LineView]:
    return _line_views(manager_repo.lines(), today_figures(calendar, now))


def today_figures(calendar: MarketCalendar, now: datetime) -> dict[str, DayFigure | None]:
    """Today's money by line key, market apart from charges (ADR 42): each
    strategy's (today's fills, whenever their run started) and the desk's
    (the latest minute recorded, open positions included)."""
    figures: dict[str, DayFigure | None] = {
        f"{LineKind.STRATEGY.value}:{row.strategy.id}": row.today
        for row in strategy_board(calendar, now)
    }
    points = pnl_repo.points_on(trading_day(now, calendar))
    figures[LineKind.DESK.value] = DayFigure.of(points[-1]) if points else None
    return figures


@dataclass(frozen=True)
class _Day:
    """A trading day of the manager's: its threads and every turn of them."""

    threads: list[AgentThread]  # oldest first
    turns: list[AgentJob]  # of every thread of the day, first asked first
    needs_plan: bool  # no thread, or the newest's first turn failed with no conversation

    @property
    def thread(self) -> AgentThread | None:
        """The newest: the one a wake goes to."""
        return self.threads[-1] if self.threads else None

    @property
    def wakes(self) -> int:
        return sum(1 for turn in self.turns if is_wake(turn.trigger))

    @property
    def open(self) -> bool:
        return any(turn.status is not AgentJobStatus.ENDED for turn in self.turns)

    @property
    def failures(self) -> int:
        return trailing_failures([turn.end_reason for turn in self.turns])

    @property
    def last_failed(self) -> AgentJob | None:
        ended = [turn for turn in self.turns if turn.end_reason is not None]
        return ended[-1] if self.failures and ended else None


def _day(day: date, session: Session | None = None) -> _Day:
    """The manager's trading day: its threads and every turn of them."""
    threads = agent_threads_repo.manager_threads(day, session)
    turns_by_thread = {t.id: agent_jobs_repo.turns_of(t.id, session) for t in threads}
    turns = sorted(
        (turn for found in turns_by_thread.values() for turn in found),
        key=lambda turn: turn.created_at,
    )
    newest = threads[-1] if threads else None
    newest_turns = turns_by_thread[newest.id] if newest else []
    needs_plan = newest is None or (
        newest.session_id is None
        and bool(newest_turns)
        and all(turn.end_reason is not None for turn in newest_turns)
        and not any(turn.end_reason is AgentJobEndReason.FINISHED for turn in newest_turns)
    )
    return _Day(threads, turns, needs_plan)


def _name(line: ManagerLine) -> str | None:
    if line.key.id is None:
        return None
    if line.key.kind is LineKind.STRATEGY:
        strategy = find_strategy(line.key.id)
        return strategy.name if strategy else None
    script = find_script(line.key.id)
    return script.name if script else None


# --- the daemon's side ---


def queue_due_manager_wake(context: AgentContext, now: datetime) -> AgentJob | None:
    """A turn of today's thread when the manager is due to look (wake_due),
    opening the thread on the day's first. Called each minute by the daemon;
    the chat lane starts the turn. What broke since its last wake is read
    from the audit log after `last_audit_id`; lines are judged against
    today's figures. Between wakes, entries that broke nothing are passed
    over, and a line that recovered can wake it again. A failed turn is
    tried again after RETRY_AFTER; once it keeps failing, or the day's
    wakes are used up, the user is told once (ManagerStalled)."""
    if not manager_repo.get_state().enabled:
        return None
    calendar = load_calendar()
    day = now.astimezone(EXCHANGE_TIMEZONE).date()
    hours = session_hours(day, Exchange.NSE, calendar)
    seen = manager_repo.get_state().last_audit_id
    scanned = list_audit(MAX_SCANNED, event_types=BROKE_EVENTS, after_id=seen, oldest_first=True)
    broken = tuple(found for entry in scanned if (found := _broke(entry)))
    lines = manager_repo.lines()
    figures: dict[str, DayFigure | None] = (
        today_figures(calendar, now) if any(l.stop is not None for l in lines) else {}
    )
    crossed_now = crossed_lines(lines, figures)
    notice: ManagerStalled | None = None
    with write_transaction() as session:
        state = manager_repo.get_state(session)
        if state.last_audit_id != seen:  # judged meanwhile: wait for the next pass
            return None
        today = _day(day, session)
        failed = today.last_failed
        decision = wake_due(
            WakeInputs(
                now=now,
                hours=hours,
                state=state,
                needs_plan=today.needs_plan,
                turn_open=today.open,
                wakes_today=today.wakes,
                failures=today.failures,
                last_failed_at=failed.ended_at if failed else None,
                last_failed_reason=wake_reason(failed.trigger) if failed else None,
                broken=broken,
                crossed_now=crossed_now,
            )
        )
        stall = stalled(decision.outcome, today.failures)
        if stall is not None and stall != state.stalled:
            notice = ManagerStalled(
                stall.value,
                _stall_detail(stall, today.failures, failed, state.wakes_per_day),
                today.thread.id if today.thread else None,
            )
        if decision.outcome is not WakeOutcome.DUE or decision.reason is None:
            between = replace(
                state,
                # Nothing that broke waits: what was read is judged.
                last_audit_id=scanned[-1].id if scanned and not broken else seen,
                crossed=state.crossed & crossed_now,  # a line that recovered can cross again
                stalled=stall.value if stall else None,
            )
            if between != state:
                manager_repo.save_state(session, between)
            job = None
        else:
            reason = decision.reason
            named = {str(v.line.key): v for v in _line_views(lines, figures)}
            since, facts, last_close = (
                _plan_facts(calendar, day)
                if reason is WakeReason.PLAN
                else (None, digest(broken, day) if reason is WakeReason.BROKE else [], None)
            )
            message = wake_message(
                reason,
                day,
                next_wake_reason=state.next_wake_reason,
                facts=facts,
                since=since,
                last_close=last_close,
                crossed=[
                    Crossed(
                        key, _label(named[key]), _net(figures[key]), named[key].line.stop or 0.0
                    )
                    for key in sorted(decision.newly_crossed)
                ],
            )
            if decision.retry and failed is not None:
                again = failed.prompt if failed.prompt and reason is not WakeReason.PLAN else None
                message = retry_message(
                    _without_retry(again) if again else message,
                    today.failures,
                    (failed.end_detail or failed.end_reason or "")[:200] or None,
                )
            thread, job = _add_wake(session, context.settings, today, day, reason, message, now)
            consumed = reason in (WakeReason.PLAN, WakeReason.SCHEDULED)
            manager_repo.save_state(
                session,
                replace(
                    state,
                    last_wake_at=now,
                    next_wake_at=None if consumed else state.next_wake_at,
                    next_wake_reason=None if consumed else state.next_wake_reason,
                    closed_on=day if reason is WakeReason.CLOSE else state.closed_on,
                    # The plan reads the whole desk: nothing before it is news.
                    last_audit_id=(
                        _newest_audit_id()
                        if reason is WakeReason.PLAN
                        else (scanned[-1].id if scanned else seen)
                    ),
                    crossed=crossed_now,
                    stalled=stall.value if stall else None,
                    updated_at=now,
                ),
            )
    if notice is not None:
        log.warning("desk manager stalled (%s): %s", notice.why, notice.detail)
        context.events.publish(notice)
    if job is None:
        return None
    log.info("desk manager woke (%s): job %s in %s", reason, job.id, thread.id)
    context.events.publish(ManagerWoke(reason.value, message, thread.id, job.id))
    return job


def _add_wake(
    session: Session,
    settings: AgentSettings,
    today: _Day,
    day: date,
    reason: WakeReason,
    message: str,
    now: datetime,
) -> tuple[AgentThread, AgentJob]:
    """A wake's turn, in today's thread; a new one for the day's first, or
    when the first turn left no conversation to resume."""
    choice = run_choice(settings, look_kind(wake_trigger(reason)))
    harness = choice.harness or settings.harness
    thread = today.thread
    if thread is None or today.needs_plan:
        thread = agent_threads_repo.add_thread(
            session, Folder.MANAGER, day.isoformat(), harness, _thread_title(day), now
        )
    same = thread.harness is harness  # a model chosen for another harness won't do
    job = agent_jobs_repo.add_job(
        session,
        AgentJobKind.CHAT,
        None,
        thread.harness,
        wake_trigger(reason),
        now,
        thread_id=thread.id,
        prompt=message,
        model=choice.model if same else None,
        effort=(choice.effort or None) if same else None,
    )
    agent_threads_repo.touch(session, thread.id, now)
    return thread, job


def _without_retry(prompt: str) -> str:
    """A failed turn's wake, without the note an earlier retry put on it."""
    if prompt.startswith("Retry: ") and "\n" in prompt:
        return prompt.split("\n", 1)[1]
    return prompt


def _stall_detail(why: Stalled, failures: int, failed: AgentJob | None, wakes_per_day: int) -> str:
    if why is Stalled.CAPPED:
        return (
            f"It used its {wakes_per_day} wakes today and won't wake again until tomorrow's "
            "plan. Raise its wakes a day on the Manager page to let it go on."
        )
    every = int(retry_gap(failures).total_seconds() // 60)
    latest = (failed.end_detail or failed.end_reason or "") if failed else ""
    return (
        f"Its last {failures} turns failed (latest: {latest or 'no detail'}). It tries again "
        f"every {every} minutes; the Manager page shows its thread and the Agents page its log."
    )


MAX_SCANNED = 500  # audit entries read in one pass; the rest on the next


def _broke(entry: AuditEntry) -> Broke | None:
    return broke(entry.id, entry.event_type, entry.triggered_by, _payload(entry), entry.occurred_at)


def _plan_facts(
    calendar: MarketCalendar, day: date
) -> tuple[datetime | None, list[DigestLine], CloseNote | None]:
    """What the plan is told: what broke since the previous session closed,
    turned on or not (a Monday's plan reads from Friday's close), and what
    the manager answered at that close."""
    midnight = datetime.combine(day, time(), EXCHANGE_TIMEZONE)
    previous = last_session(midnight, Exchange.NSE, calendar)
    if previous is None:
        return None, [], None
    scanned = list_audit(
        MAX_SCANNED, event_types=BROKE_EVENTS, since=previous.closes_at, oldest_first=True
    )
    broken = [found for entry in scanned if (found := _broke(entry))]
    return previous.closes_at, digest(broken, day), _close_note(previous.day)


def _close_note(day: date) -> CloseNote:
    """The answer of that day's close wake, if one finished."""
    for thread in reversed(agent_threads_repo.manager_threads(day)):
        for job in reversed(agent_jobs_repo.turns_of(thread.id)):
            if (
                wake_reason(job.trigger) is WakeReason.CLOSE
                and job.end_reason is AgentJobEndReason.FINISHED
                and job.summary
            ):
                return CloseNote(day, job.summary)
    return CloseNote(day, None)


def _payload(entry: AuditEntry) -> dict[str, object]:
    try:
        found = json.loads(entry.payload)
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


def _newest_audit_id() -> int:
    newest = list_audit(1)
    return newest[0].id if newest else 0


def _net(figure: DayFigure | None) -> float:
    return figure.net if figure else 0.0


def _line_views(lines: list[ManagerLine], figures: dict[str, DayFigure | None]) -> list[LineView]:
    crossed = crossed_lines(lines, figures)
    return [
        LineView(line, _name(line), figures.get(str(line.key)), str(line.key) in crossed)
        for line in lines
    ]


def _label(view: LineView) -> str:
    kind = view.line.key.kind
    if kind is LineKind.DESK:
        return "The desk"
    if kind is LineKind.OWN:
        return "Your own trades"
    name = view.name or str(view.line.key)
    return f"{kind.value.capitalize()} {name!r} ({view.line.key.id})"


def _thread_title(day: date) -> str:
    return f"Desk, {day.strftime('%a %d %b')}"


# --- the tools' side ---


def set_next_wake(
    at: datetime, reason: str, calendar: MarketCalendar, now: datetime
) -> ManagerState:
    """When the manager looks next, today. Replaces the time it set before."""
    reason = reason.strip()
    if not reason:
        raise ManagerError("say why then: the user reads it")
    if len(reason) > MAX_REASON_CHARS:
        raise ManagerError(f"a reason is at most {MAX_REASON_CHARS} characters")
    day = now.astimezone(EXCHANGE_TIMEZONE).date()
    check_next_wake(at, now, session_hours(day, Exchange.NSE, calendar))
    with write_transaction() as session:
        state = replace(
            manager_repo.get_state(session),
            next_wake_at=at,
            next_wake_reason=reason,
            updated_at=now,
        )
        manager_repo.save_state(session, state)
    return state


def set_plan(
    text: str,
    lesson_ids: Sequence[str],
    events: EventPublisher,
    triggered_by: str,
    now: datetime,
) -> ManagerPlan:
    """Today's plan, with the brain's lessons it relied on."""
    text = text.strip()
    ids = tuple(dict.fromkeys(i.strip() for i in lesson_ids if i.strip()))
    check_plan(text, ids)
    for lesson_id in ids:
        note = brain_repo.get_note(lesson_id)
        if note is None or note.kind is not NoteKind.LESSON:
            raise UnknownNoteError(f"no lesson {lesson_id}; search_brain(kind=lesson) finds them")
    plan = ManagerPlan(now.astimezone(EXCHANGE_TIMEZONE).date(), text, ids, now)
    with write_transaction() as session:
        state = manager_repo.get_state(session)
        manager_repo.save_state(session, replace(state, plan=plan, updated_at=now))
    events.publish(ManagerPlanSet(plan.day, text, ids, triggered_by))
    return plan


# --- the user's side ---


def set_manager(
    enabled: bool,
    wakes_per_day: int | None,
    events: EventPublisher,
    triggered_by: str,
    now: datetime,
) -> ManagerState:
    """Turns the manager on or off. Off stops its wakes; a turn already
    running finishes, and nothing it started is stopped."""
    with write_transaction() as session:
        state = manager_repo.get_state(session)
        if wakes_per_day is not None and not 1 <= wakes_per_day <= MAX_WAKES_PER_DAY:
            raise ManagerError(f"wakes a day are 1 to {MAX_WAKES_PER_DAY}")
        turned_on = enabled and not state.enabled
        state = replace(
            state,
            enabled=enabled,
            wakes_per_day=wakes_per_day or state.wakes_per_day,
            # What broke before it was on isn't its to wake for.
            last_audit_id=_newest_audit_id() if turned_on else state.last_audit_id,
            updated_at=now,
        )
        manager_repo.save_state(session, state)
    events.publish(ManagerSwitched(enabled, state.wakes_per_day, triggered_by))
    return state


class ManagerOffError(Exception):
    """Look now while the manager is off."""


def wake_manager(
    settings: AgentSettings, events: EventPublisher, triggered_by: str, now: datetime
) -> AgentJob:
    """Look now: a turn of today's thread at once, opening it if needed.
    Counts against the day's wakes. Refused while the manager is off, or
    while a turn of its waits or runs."""
    day = now.astimezone(EXCHANGE_TIMEZONE).date()
    with write_transaction() as session:
        state = manager_repo.get_state(session)
        if not state.enabled:
            raise ManagerOffError("the manager is off: turn it on first")
        today = _day(day, session)
        if today.open:
            raise AgentJobBusyError("the manager is already looking: its turn waits or runs")
        if today.wakes >= state.wakes_per_day:
            raise AgentJobCapError(
                f"the manager used its {state.wakes_per_day} wakes today; raise its wakes a day"
            )
        message = wake_message(WakeReason.ASKED, day)
        thread, job = _add_wake(session, settings, today, day, WakeReason.ASKED, message, now)
        manager_repo.save_state(session, replace(state, last_wake_at=now, updated_at=now))
    log.info("desk manager asked to look by %s: job %s in %s", triggered_by, job.id, thread.id)
    events.publish(ManagerWoke(WakeReason.ASKED.value, message, thread.id, job.id))
    return job
