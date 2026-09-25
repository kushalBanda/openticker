"""Reviews on the user's schedule (ADR 29): the daemon asks for one when a
strategy's trigger is met, as start_review would."""

from datetime import timedelta
from pathlib import Path

import pytest

from openticker.adapters.sandbox.broker import SandboxSettings
from openticker.core.agents.jobs import AgentJobStatus, AgentSettings, Harness
from openticker.core.agents.reviews import ReviewScheduleError
from openticker.core.orders.fills import FillSettings
from openticker.use_cases.agents.manage import (
    get_agent_jobs,
    schedule_review,
    start_review,
    unschedule_review,
)
from openticker.use_cases.agents.supervise import (
    AgentContext,
    queue_due_reviews,
    start_next_job,
    watch_jobs,
)
from openticker.use_cases.strategies.control import request_start, request_stop
from openticker.use_cases.strategies.define import (
    UnknownStrategyError,
    delete_strategy,
    get_strategy,
)
from openticker.use_cases.strategies.runner import process_commands
from tests.fixtures.strategy_desk import Desk
from tests.use_cases.agents.test_agent_jobs import _Events, _Processes

SETTINGS = AgentSettings(harness=Harness.CLAUDE, jobs_per_day=5)


@pytest.fixture
def desk() -> Desk:
    return Desk(SandboxSettings(fills=FillSettings(slippage_ticks=1)))  # real charges


def _context(
    tmp_path: Path, settings: AgentSettings = SETTINGS, processes: _Processes | None = None
) -> AgentContext:
    return AgentContext(
        processes or _Processes(), _Events(), settings, tmp_path, "http://127.0.0.1:8750/mcp"
    )


def _one_more_run(desk: Desk, strategy_id: str) -> None:
    """A few minutes on, ends the open run and starts the next."""
    desk.now += timedelta(minutes=5)
    request_stop(strategy_id, "mcp", desk.now)
    process_commands(desk.context, desk.now)
    desk.now += timedelta(minutes=5)
    request_start(strategy_id, "fake", "mcp", desk.now)
    process_commands(desk.context, desk.now)


def test_a_schedule_is_kept_with_the_strategy_until_turned_off(desk: Desk) -> None:
    strategy_id = desk.start()  # running: a schedule can still be set

    schedule_review(strategy_id, "4h", 10, 3_000, desk.now)

    stored = get_strategy(strategy_id)
    assert stored.review_schedule is not None
    assert stored.review_schedule.every == timedelta(hours=4)
    assert (stored.review_schedule.after_runs, stored.review_schedule.drawdown) == (10, 3_000)
    assert stored.review_schedule.set_at == desk.now
    assert unschedule_review(strategy_id).review_schedule is None


def test_a_schedule_refuses_what_it_cant_keep(desk: Desk) -> None:
    strategy_id = desk.start()

    with pytest.raises(ReviewScheduleError, match="at least one"):
        schedule_review(strategy_id, None, None, None, desk.now)
    with pytest.raises(ReviewScheduleError, match="like 30m"):
        schedule_review(strategy_id, "daily", None, None, desk.now)
    with pytest.raises(UnknownStrategyError):
        schedule_review("stg_nope", "1d", None, None, desk.now)


def test_a_due_review_is_asked_for_once_and_says_why(desk: Desk, tmp_path: Path) -> None:
    strategy_id = desk.start()
    schedule_review(strategy_id, None, 2, None, desk.now)
    processes = _Processes()
    context = _context(tmp_path, processes=processes)
    _one_more_run(desk, strategy_id)

    assert queue_due_reviews(context, desk.now) == []  # one run ended so far
    _one_more_run(desk, strategy_id)
    [job] = queue_due_reviews(context, desk.now)
    assert job.trigger == "schedule: 2 runs after costs since the last review"
    assert queue_due_reviews(context, desk.now) == []  # already waiting

    start_next_job(context, desk.now)
    [launch] = processes.launches
    assert "due on its review schedule: 2 runs after costs" in launch.prompt


def test_a_review_asked_for_by_hand_restarts_the_count(desk: Desk, tmp_path: Path) -> None:
    strategy_id = desk.start()
    schedule_review(strategy_id, None, 2, None, desk.now)
    _one_more_run(desk, strategy_id)
    _one_more_run(desk, strategy_id)
    desk.now += timedelta(minutes=1)
    job = start_review(strategy_id, SETTINGS, "mcp", desk.now)
    processes = _Processes()
    context = _context(tmp_path, processes=processes)
    processes.exited[1001] = 0
    start_next_job(context, desk.now)
    watch_jobs(context, desk.now)

    assert get_agent_jobs(10, strategy_id)[0].id == job.id
    assert queue_due_reviews(context, desk.now + timedelta(minutes=1)) == []


def test_the_days_cap_leaves_a_review_due_for_later(desk: Desk, tmp_path: Path) -> None:
    strategy_id = desk.start()
    schedule_review(strategy_id, None, 1, None, desk.now)
    capped = AgentSettings(jobs_per_day=1)
    context = _context(tmp_path, capped)
    other = desk.start(name="other")
    start_review(other, capped, "mcp", desk.now)
    start_next_job(context, desk.now)  # the day's one job
    _one_more_run(desk, strategy_id)

    assert queue_due_reviews(context, desk.now) == []
    assert get_agent_jobs(10, strategy_id) == []  # nothing refused, nothing queued

    desk.now += timedelta(days=1)
    assert [job.status for job in queue_due_reviews(context, desk.now)] == [AgentJobStatus.PENDING]


def test_a_deleted_or_unscheduled_strategy_is_not_reviewed(desk: Desk, tmp_path: Path) -> None:
    strategy_id = desk.start()
    schedule_review(strategy_id, None, 1, None, desk.now)
    _one_more_run(desk, strategy_id)
    unschedule_review(strategy_id)

    assert queue_due_reviews(_context(tmp_path), desk.now) == []

    schedule_review(strategy_id, None, 1, None, desk.now - timedelta(hours=1))
    request_stop(strategy_id, "mcp", desk.now)
    process_commands(desk.context, desk.now)
    delete_strategy(strategy_id, desk.now)

    assert queue_due_reviews(_context(tmp_path), desk.now) == []


def test_jobs_waiting_count_against_the_cap_so_a_review_stays_due(
    desk: Desk, tmp_path: Path
) -> None:
    strategy_id = desk.start()
    schedule_review(strategy_id, None, 1, None, desk.now)
    capped = AgentSettings(jobs_per_day=1)
    start_review(desk.start(name="other"), capped, "mcp", desk.now)  # waiting, not started
    _one_more_run(desk, strategy_id)

    assert queue_due_reviews(_context(tmp_path, capped), desk.now) == []
    assert get_agent_jobs(10, strategy_id) == []


def test_a_review_refused_before_it_started_doesnt_restart_the_count(
    desk: Desk, tmp_path: Path
) -> None:
    strategy_id = desk.start()
    schedule_review(strategy_id, None, 1, None, desk.now)
    _one_more_run(desk, strategy_id)
    capped = AgentSettings(jobs_per_day=1)
    start_review(strategy_id, SETTINGS, "mcp", desk.now)  # asked by hand past the cap below
    processes = _Processes()
    context = _context(tmp_path, capped, processes)
    start_review(desk.start(name="other"), capped, "mcp", desk.now - timedelta(minutes=1))
    start_next_job(context, desk.now)  # the other job: the day's one
    processes.exited[1001] = 0
    watch_jobs(context, desk.now)
    start_next_job(context, desk.now)  # ours: refused, the cap has run

    assert get_agent_jobs(1, strategy_id)[0].end_reason == "refused"
    desk.now += timedelta(days=1)
    assert len(queue_due_reviews(context, desk.now)) == 1
