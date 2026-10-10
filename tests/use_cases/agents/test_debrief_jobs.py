"""The daily debrief as an agent job: due after the close, queued once a day,
a quiet day noted without one, and started with the debrief agent and a
key for its own day. Reviews are unchanged."""

from datetime import date, time, timedelta
from pathlib import Path

import pytest

from openticker.adapters.inbound.mcp_models import AgentJobResult
from openticker.core.agents.jobs import AgentJobEndReason, AgentJobKind, AgentJobStatus
from openticker.core.brain.notes import NoteKind
from openticker.core.calendar.models import MarketCalendar
from openticker.core.pnl import DayPnl
from openticker.events.types import AgentJobEnded, AgentJobStarted, DebriefWritten
from openticker.storage.sqlite import agent_jobs_repo, brain_repo, pnl_repo, strategies_repo
from openticker.storage.sqlite.strategies_repo import write_transaction
from openticker.use_cases.agents.manage import (
    AgentJobBusyError,
    AgentJobCapError,
    get_agent_jobs,
    start_review,
    strategy_names,
)
from openticker.use_cases.agents.supervise import queue_due_debrief, start_next_job, watch_jobs
from openticker.use_cases.api_keys import authenticate
from openticker.use_cases.brain.debrief import QUIET_HEADLINE, latest_closed_day, start_debrief
from openticker.use_cases.strategies.define import create_strategy
from tests.fixtures.brain_day import monday
from tests.fixtures.pnl_desk import MONDAY, TUESDAY, at
from tests.fixtures.strategies import STRADDLE, list_nifty_market
from tests.use_cases.agents.test_agent_jobs import SETTINGS, _context, _Events, _Processes

CALENDAR = MarketCalendar(years=frozenset({2026}), holidays=(), special_sessions=())
AFTER_CLOSE = at(MONDAY, 16, 0)


def _scheduled(at_: time = time(15, 45)) -> None:
    with write_transaction() as session:
        brain_repo.set_debrief_at(session, at_)


def _recorded() -> None:
    pnl_repo.upsert_day(DayPnl(MONDAY, 120.0, 30.0, 0.0, 90.0, 0.0, 4, True), AFTER_CLOSE)


def test_queue_due_debrief_queues_once_per_day(tmp_path: Path) -> None:
    monday()
    context = _context(_Processes(), _Events(), tmp_path)
    assert queue_due_debrief(context, AFTER_CLOSE) is None  # off
    _scheduled()
    assert queue_due_debrief(context, AFTER_CLOSE) is None  # the day's P&L isn't recorded
    _recorded()
    assert queue_due_debrief(context, at(MONDAY, 15, 44)) is None  # before its time

    job = queue_due_debrief(context, AFTER_CLOSE)

    assert job is not None and (job.kind, job.subject, job.strategy_id) == (
        AgentJobKind.DEBRIEF,
        MONDAY,
        None,
    )
    assert job.trigger == "schedule: after the close"
    assert queue_due_debrief(context, at(MONDAY, 16, 1)) is None  # once a day


def test_quiet_day_note_written_without_job(tmp_path: Path) -> None:
    _scheduled()
    _recorded()
    events = _Events()
    context = _context(_Processes(), events, tmp_path)

    assert queue_due_debrief(context, AFTER_CLOSE) is None

    note = brain_repo.find_note(NoteKind.DAY, MONDAY.isoformat())
    assert note is not None and note.data["headline"] == QUIET_HEADLINE
    assert note.written_by.value == "server"
    [written] = events.of(DebriefWritten)
    assert isinstance(written, DebriefWritten) and written.quiet
    assert get_agent_jobs(10) == []
    assert queue_due_debrief(context, at(MONDAY, 16, 1)) is None
    assert len(events.of(DebriefWritten)) == 1  # noted once


def test_debrief_job_starts_without_strategy_and_launches_debrief_agent_without_note_writes(
    tmp_path: Path,
) -> None:
    monday()
    job = start_debrief(MONDAY, SETTINGS, "mcp:claude-code", AFTER_CLOSE, CALENDAR)
    processes, events = _Processes(), _Events()
    context = _context(processes, events, tmp_path)

    start_next_job(context, AFTER_CLOSE)

    [launch] = processes.launches
    key = authenticate(launch.api_key)
    assert key is not None and key.scope == "debrief:2026-09-21"
    assert (launch.agent, launch.writes_notes) == ("debrief", False)
    assert "debrief-day skill" in launch.prompt and "2026-09-21" in launch.prompt
    assert f"agent job {job.id}" in launch.prompt
    [started] = events.of(AgentJobStarted)
    assert isinstance(started, AgentJobStarted)
    assert (started.strategy_id, started.subject, started.title) == (
        None,
        MONDAY,
        "Debrief of Mon 21 Sep",
    )

    processes.exited[1001] = 0
    watch_jobs(context, at(MONDAY, 16, 5))
    [ended] = events.of(AgentJobEnded)
    assert isinstance(ended, AgentJobEnded) and ended.title == "Debrief of Mon 21 Sep"
    assert authenticate(launch.api_key) is None  # revoked


def test_debrief_job_counts_toward_daily_cap(tmp_path: Path) -> None:
    list_nifty_market()
    for n in range(SETTINGS.jobs_per_day):
        stored = create_strategy(f"s{n}", STRADDLE, AFTER_CLOSE)
        start_review(stored.id, SETTINGS, "mcp", AFTER_CLOSE)
        processes = _Processes()
        context = _context(processes, _Events(), tmp_path)
        start_next_job(context, AFTER_CLOSE)
        processes.exited[1001] = 0
        watch_jobs(context, AFTER_CLOSE)

    with pytest.raises(AgentJobCapError, match="daily cap"):
        start_debrief(MONDAY, SETTINGS, "mcp", AFTER_CLOSE, CALENDAR)


def test_start_debrief_defaults_to_latest_closed_trading_day() -> None:
    assert latest_closed_day(at(TUESDAY, 15, 29), CALENDAR) == MONDAY
    assert latest_closed_day(at(TUESDAY, 15, 30), CALENDAR) == TUESDAY
    assert latest_closed_day(at(MONDAY, 9, 0), CALENDAR) == date_before(MONDAY)

    job = start_debrief(None, SETTINGS, "ui", at(TUESDAY, 10, 0), CALENDAR)

    assert job.subject == MONDAY


def test_start_debrief_refused_while_one_for_date_pending() -> None:
    start_debrief(MONDAY, SETTINGS, "ui", AFTER_CLOSE, CALENDAR)

    with pytest.raises(AgentJobBusyError, match="already pending"):
        start_debrief(MONDAY, SETTINGS, "ui", AFTER_CLOSE, CALENDAR)
    start_debrief(date_before(MONDAY), SETTINGS, "ui", AFTER_CLOSE, CALENDAR)  # another day


def test_get_agent_jobs_returns_desk_jobs_with_title() -> None:
    list_nifty_market()
    stored = create_strategy("straddle", STRADDLE, AFTER_CLOSE)
    start_review(stored.id, SETTINGS, "ui", AFTER_CLOSE)
    start_debrief(MONDAY, SETTINGS, "ui", AFTER_CLOSE, CALENDAR)

    titles = [AgentJobResult.of(j, strategy_names()).title for j in get_agent_jobs(10)]

    assert sorted(titles) == ["Debrief of Mon 21 Sep", "Review of straddle"]


def test_review_job_still_refused_when_strategy_deleted(tmp_path: Path) -> None:
    list_nifty_market()
    stored = create_strategy("straddle", STRADDLE, AFTER_CLOSE)
    job = start_review(stored.id, SETTINGS, "ui", AFTER_CLOSE)
    strategies_repo.delete_strategy(stored.id, AFTER_CLOSE)
    events = _Events()

    start_next_job(_context(_Processes(), events, tmp_path), AFTER_CLOSE)

    ended = agent_jobs_repo.find_job(job.id)
    assert ended is not None and ended.end_reason is AgentJobEndReason.REFUSED
    assert ended.end_detail == "its strategy was deleted"
    [event] = events.of(AgentJobEnded)
    assert isinstance(event, AgentJobEnded) and event.title == "Review of a deleted strategy"


def test_review_job_title_and_events_unchanged(tmp_path: Path) -> None:
    list_nifty_market()
    stored = create_strategy("straddle", STRADDLE, AFTER_CLOSE)
    start_review(stored.id, SETTINGS, "ui", AFTER_CLOSE)
    processes, events = _Processes(), _Events()

    start_next_job(_context(processes, events, tmp_path), AFTER_CLOSE)

    [launch] = processes.launches
    assert (launch.agent, launch.writes_notes) == ("reviewer", True)
    [started] = events.of(AgentJobStarted)
    assert isinstance(started, AgentJobStarted)
    assert (started.kind, started.strategy_id, started.subject, started.title) == (
        "review",
        stored.id,
        None,
        "Review of straddle",
    )
    job = agent_jobs_repo.recent_jobs(1)[0]
    assert job.status is AgentJobStatus.RUNNING and job.subject is None


def date_before(day: date) -> date:
    previous = day - timedelta(days=1)
    while previous.weekday() >= 5:
        previous -= timedelta(days=1)
    return previous
