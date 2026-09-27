from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openticker.core.agents.jobs import (
    AgentJobEndReason,
    AgentJobStatus,
    AgentSettings,
    Harness,
)
from openticker.events.types import AgentJobEnded, AgentJobStarted
from openticker.ports.agent_job_port import AgentLaunch, AgentOutcome
from openticker.ports.script_process_port import Exited
from openticker.storage import agent_job_files
from openticker.storage.sqlite import agent_jobs_repo
from openticker.use_cases.agents.manage import (
    AgentJobBusyError,
    AgentJobCapError,
    UnknownAgentJobError,
    get_agent_job_log,
    get_agent_jobs,
    start_review,
    stop_agent_job,
)
from openticker.use_cases.agents.supervise import (
    STOP_GRACE,
    AgentContext,
    recover_jobs,
    start_next_job,
    stop_all_jobs,
    watch_jobs,
)
from openticker.use_cases.api_keys import authenticate
from openticker.use_cases.strategies.define import UnknownStrategyError, create_strategy
from tests.fixtures.strategies import STRADDLE, list_nifty_market

NOW = datetime(2026, 9, 22, 4, 0, tzinfo=UTC)
SETTINGS = AgentSettings(harness=Harness.CLAUDE, timeout=timedelta(minutes=15), jobs_per_day=3)


class _Events:
    def __init__(self) -> None:
        self.events: list[object] = []

    def publish(self, event: object) -> None:
        self.events.append(event)

    def of(self, kind: type) -> list[object]:
        return [event for event in self.events if isinstance(event, kind)]


class _Processes:
    """Processes that run until a test says they exited."""

    def __init__(self) -> None:
        self.launches: list[AgentLaunch] = []
        self.exited: dict[int, int | None] = {}
        self.stopped: list[tuple[int, bool]] = []
        self.ours: set[int] = set()
        self.answer = AgentOutcome("keep: net ₹1,200 over 12 runs", 0.42)
        self.fail_start = False

    def start(self, launch: AgentLaunch) -> int:
        if self.fail_start:
            raise FileNotFoundError("claude is not on PATH")
        self.launches.append(launch)
        pid = 1000 + len(self.launches)
        self.ours.add(pid)
        return pid

    def poll(self, pid: int) -> Exited | None:
        return Exited(self.exited[pid]) if pid in self.exited else None

    def is_job(self, pid: int, job_id: str) -> bool:
        return pid in self.ours

    def stop(self, pid: int, force: bool) -> None:
        self.stopped.append((pid, force))

    def outcome(self, harness: Harness, result_path: Path) -> AgentOutcome:
        return self.answer


def _context(processes: _Processes, events: _Events, tmp_path: Path) -> AgentContext:
    return AgentContext(processes, events, SETTINGS, tmp_path, "http://127.0.0.1:8750/mcp")


@pytest.fixture(autouse=True)
def _market() -> None:
    list_nifty_market()


def _strategy(name: str = "straddle") -> str:
    return create_strategy(name, STRADDLE, NOW).id


def test_a_review_waits_for_the_daemon_and_one_per_strategy() -> None:
    strategy_id = _strategy()

    job = start_review(strategy_id, SETTINGS, "mcp", NOW)

    assert (job.status, job.harness, job.trigger) == (AgentJobStatus.PENDING, Harness.CLAUDE, "mcp")
    with pytest.raises(AgentJobBusyError, match="already pending"):
        start_review(strategy_id, SETTINGS, "mcp", NOW)
    with pytest.raises(UnknownStrategyError):
        start_review("stg_nope", SETTINGS, "mcp", NOW)


def test_the_daemon_starts_it_with_a_key_that_reads_only_that_strategy(tmp_path: Path) -> None:
    strategy_id = _strategy()
    job = start_review(strategy_id, SETTINGS, "mcp", NOW)
    processes, events = _Processes(), _Events()

    start_next_job(_context(processes, events, tmp_path), NOW)

    [launch] = processes.launches
    key = authenticate(launch.api_key)
    assert key is not None and key.scope == f"review:{strategy_id}"
    assert f"agent job {job.id}" in launch.prompt and "notes/straddle.md" in launch.prompt
    assert (launch.labs_dir, launch.mcp_url) == (tmp_path, "http://127.0.0.1:8750/mcp")
    running = agent_jobs_repo.find_job(job.id)
    assert running is not None and running.status is AgentJobStatus.RUNNING
    assert len(events.of(AgentJobStarted)) == 1


def test_one_job_runs_at_a_time(tmp_path: Path) -> None:
    first = start_review(_strategy("a"), SETTINGS, "mcp", NOW)
    second = start_review(_strategy("b"), SETTINGS, "mcp", NOW)
    processes, events = _Processes(), _Events()
    context = _context(processes, events, tmp_path)

    start_next_job(context, NOW)
    start_next_job(context, NOW)
    assert [launch.job_id for launch in processes.launches] == [first.id]

    processes.exited[1001] = 0
    watch_jobs(context, NOW)
    start_next_job(context, NOW)
    assert [launch.job_id for launch in processes.launches] == [first.id, second.id]


def test_an_ended_job_keeps_its_answer_and_cost_revokes_its_key_and_notifies(
    tmp_path: Path,
) -> None:
    job = start_review(_strategy(), SETTINGS, "mcp", NOW)
    processes, events = _Processes(), _Events()
    context = _context(processes, events, tmp_path)
    start_next_job(context, NOW)

    processes.exited[1001] = 0
    watch_jobs(context, NOW + timedelta(minutes=3))

    ended = agent_jobs_repo.find_job(job.id)
    assert ended is not None
    assert (ended.status, ended.end_reason) == (AgentJobStatus.ENDED, AgentJobEndReason.FINISHED)
    assert (ended.summary, ended.cost_usd) == ("keep: net ₹1,200 over 12 runs", 0.42)
    assert authenticate(processes.launches[0].api_key) is None
    [event] = events.of(AgentJobEnded)
    assert isinstance(event, AgentJobEnded)
    assert (event.strategy_name, event.reason, event.cost_usd) == ("straddle", "finished", 0.42)
    assert f"job {job.id} ended: finished" in get_agent_job_log(job.id).text


def test_a_job_past_its_timeout_is_stopped_then_killed(tmp_path: Path) -> None:
    job = start_review(_strategy(), SETTINGS, "mcp", NOW)
    processes, events = _Processes(), _Events()
    context = _context(processes, events, tmp_path)
    start_next_job(context, NOW)

    watch_jobs(context, NOW + timedelta(minutes=14))
    assert processes.stopped == []
    late = NOW + timedelta(minutes=15)
    watch_jobs(context, late)
    watch_jobs(context, late + STOP_GRACE)
    processes.exited[1001] = -9
    watch_jobs(context, late + STOP_GRACE)

    assert processes.stopped == [(1001, False), (1001, True)]
    ended = agent_jobs_repo.find_job(job.id)
    assert ended is not None and ended.end_reason is AgentJobEndReason.TIMEOUT
    assert ended.end_detail == "still running after 15 minutes; killed by SIGKILL"


def test_a_waiting_job_stopped_ends_at_once_and_is_never_started(tmp_path: Path) -> None:
    job = start_review(_strategy(), SETTINGS, "mcp", NOW)
    processes, events = _Processes(), _Events()

    stopped = stop_agent_job(job.id, events, "ui", NOW)
    start_next_job(_context(processes, events, tmp_path), NOW)

    assert (stopped.status, stopped.end_reason) == (AgentJobStatus.ENDED, AgentJobEndReason.STOPPED)
    assert stopped.end_detail == "stopped by ui before it started"
    assert processes.launches == []
    [ended] = events.of(AgentJobEnded)
    assert isinstance(ended, AgentJobEnded) and ended.strategy_name == "straddle"


def test_a_running_job_stopped_gets_sigterm_then_sigkill(tmp_path: Path) -> None:
    job = start_review(_strategy(), SETTINGS, "mcp", NOW)
    processes, events = _Processes(), _Events()
    context = _context(processes, events, tmp_path)
    start_next_job(context, NOW)

    asked = stop_agent_job(job.id, events, "mcp:claude-code", NOW)
    watch_jobs(context, NOW + timedelta(seconds=1))
    watch_jobs(context, NOW + STOP_GRACE)
    processes.exited[1001] = -9
    watch_jobs(context, NOW + STOP_GRACE)

    assert asked.status is AgentJobStatus.STOPPING
    assert processes.stopped == [(1001, False), (1001, True)]
    ended = agent_jobs_repo.find_job(job.id)
    assert ended is not None and ended.end_reason is AgentJobEndReason.STOPPED
    assert ended.end_detail == "stopped by mcp:claude-code; killed by SIGKILL"


def test_stopping_an_ended_job_changes_nothing_and_an_unknown_one_says_where_to_look(
    tmp_path: Path,
) -> None:
    job = start_review(_strategy(), SETTINGS, "mcp", NOW)
    processes, events = _Processes(), _Events()
    context = _context(processes, events, tmp_path)
    start_next_job(context, NOW)
    processes.exited[1001] = 0
    watch_jobs(context, NOW)

    again = stop_agent_job(job.id, events, "ui", NOW)

    assert (again.status, again.end_reason) == (AgentJobStatus.ENDED, AgentJobEndReason.FINISHED)
    with pytest.raises(UnknownAgentJobError, match="get_agent_jobs"):
        stop_agent_job("agj_nope", events, "ui", NOW)


def test_the_days_cap_counts_jobs_started_today(tmp_path: Path) -> None:
    processes, events = _Processes(), _Events()
    context = _context(processes, events, tmp_path)
    for index in range(3):
        start_review(_strategy(f"s{index}"), SETTINGS, "mcp", NOW)
        start_next_job(context, NOW)
        processes.exited[1001 + index] = 0
        watch_jobs(context, NOW)

    with pytest.raises(AgentJobCapError, match="3 agent jobs have run today"):
        start_review(_strategy("s3"), SETTINGS, "mcp", NOW)
    assert start_review(_strategy("s4"), SETTINGS, "mcp", NOW + timedelta(days=1))


def test_a_job_pending_past_the_cap_is_refused_when_its_turn_comes(tmp_path: Path) -> None:
    job = start_review(_strategy(), SETTINGS, "mcp", NOW)
    processes, events = _Processes(), _Events()
    tight = replace(
        _context(processes, events, tmp_path), settings=replace(SETTINGS, jobs_per_day=1)
    )
    other = start_review(_strategy("other"), SETTINGS, "mcp", NOW + timedelta(seconds=1))
    start_next_job(tight, NOW)
    processes.exited[1001] = 0
    watch_jobs(tight, NOW)

    start_next_job(tight, NOW)

    refused = agent_jobs_repo.find_job(other.id)
    assert refused is not None and refused.end_reason is AgentJobEndReason.REFUSED
    assert [launch.job_id for launch in processes.launches] == [job.id]


def test_a_harness_that_wont_start_ends_the_job_and_its_key(tmp_path: Path) -> None:
    job = start_review(_strategy(), SETTINGS, "mcp", NOW)
    processes, events = _Processes(), _Events()
    processes.fail_start = True

    start_next_job(_context(processes, events, tmp_path), NOW)

    ended = agent_jobs_repo.find_job(job.id)
    assert ended is not None and ended.end_reason is AgentJobEndReason.START_FAILED
    assert "claude is not on PATH" in (ended.end_detail or "")


def test_after_a_restart_jobs_left_running_are_stopped_and_lost(tmp_path: Path) -> None:
    job = start_review(_strategy(), SETTINGS, "mcp", NOW)
    before, events = _Processes(), _Events()
    start_next_job(_context(before, events, tmp_path), NOW)
    after = _Processes()
    after.ours = {1001}

    recover_jobs(_context(after, events, tmp_path), NOW + timedelta(minutes=1))

    assert after.stopped == [(1001, True)]
    lost = agent_jobs_repo.find_job(job.id)
    assert lost is not None and lost.end_reason is AgentJobEndReason.LOST
    assert authenticate(before.launches[0].api_key) is None


def test_shutdown_stops_every_job(tmp_path: Path) -> None:
    job = start_review(_strategy(), SETTINGS, "mcp", NOW)
    processes, events = _Processes(), _Events()
    context = _context(processes, events, tmp_path)
    start_next_job(context, NOW)
    moments = iter([NOW + timedelta(seconds=s) for s in range(60)])

    stop_all_jobs(context, lambda: next(moments), sleep=lambda _: None)

    assert (1001, False) in processes.stopped and (1001, True) in processes.stopped
    ended = agent_jobs_repo.find_job(job.id)
    assert ended is not None and ended.end_reason is AgentJobEndReason.DAEMON_STOPPED


def test_jobs_are_listed_newest_first_and_an_unknown_log_says_where_to_look() -> None:
    first = start_review(_strategy("a"), SETTINGS, "mcp", NOW)
    second = start_review(_strategy("b"), SETTINGS, "mcp", NOW + timedelta(seconds=1))

    assert [job.id for job in get_agent_jobs(10)] == [second.id, first.id]
    assert [job.id for job in get_agent_jobs(10, first.strategy_id)] == [first.id]
    with pytest.raises(UnknownAgentJobError, match="get_agent_jobs"):
        get_agent_job_log("job_nope")


def test_a_long_log_answers_with_its_end(tmp_path: Path) -> None:
    job = start_review(_strategy(), SETTINGS, "mcp", NOW)
    agent_job_files.append_log(job.id, "x" * (agent_job_files.LOG_TAIL_BYTES + 10))
    agent_job_files.append_log(job.id, "the end")

    log = get_agent_job_log(job.id)

    assert log.truncated and log.text.endswith("the end\n")
    assert len(log.text.encode()) == agent_job_files.LOG_TAIL_BYTES


def test_after_a_restart_a_key_whose_job_already_ended_is_revoked_too(tmp_path: Path) -> None:
    from openticker.use_cases.api_keys import create_review_key

    stray = create_review_key("stg_1", "job_crashed", NOW)  # its job ended, its key didn't

    recover_jobs(_context(_Processes(), _Events(), tmp_path), NOW)

    assert authenticate(stray) is None
