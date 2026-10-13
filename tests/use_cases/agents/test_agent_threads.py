from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from openticker.core.agents.choices import Effort
from openticker.core.agents.jobs import AgentJobEndReason, AgentJobKind, AgentJobStatus
from openticker.core.agents.threads import Folder
from openticker.core.agents.transcript import StepKind
from openticker.ports.agent_job_port import AgentOutcome
from openticker.storage import agent_job_files
from openticker.storage.sqlite import agent_jobs_repo, agent_threads_repo
from openticker.use_cases.agents.manage import get_agent_jobs, start_review
from openticker.use_cases.agents.supervise import (
    recover_jobs,
    start_next_chat_turn,
    start_next_job,
    watch_jobs,
)
from openticker.use_cases.agents.threads import (
    ChatChoiceError,
    QueueFullError,
    ThreadClosedError,
    UnknownThreadError,
    list_threads,
    read_thread,
    send_message,
    start_chat,
)
from openticker.use_cases.api_keys import authenticate
from openticker.use_cases.strategies.define import UnknownStrategyError, create_strategy
from tests.fixtures.strategies import STRADDLE, list_nifty_market
from tests.use_cases.agents.test_agent_jobs import NOW, SETTINGS, _context, _Events, _Processes

FIXTURE = Path(__file__).parents[2] / "fixtures" / "transcripts" / "claude_turn.jsonl"
SESSION = "5f0c2a1e-8d3b-4c6a-9e7f-1a2b3c4d5e6f"


@pytest.fixture(autouse=True)
def _market() -> None:
    list_nifty_market()


def _chat(message: str = "Why did expiry days lose?", **kw: object) -> str:
    fields: dict[str, object] = {
        "folder": Folder.GENERAL,
        "subject": None,
        "message": message,
        "model": None,
        "effort": None,
        "settings": SETTINGS,
        "triggered_by": "ui",
        "now": NOW,
    }
    fields.update(kw)
    return start_chat(**fields).thread.id  # type: ignore[arg-type]


def _answer(processes: _Processes, pid: int, job_id: str) -> None:
    """The fake harness's turn: the recorded transcript, then exit 0."""
    agent_job_files.events_path(job_id).write_text(FIXTURE.read_text())
    processes.answer = AgentOutcome(
        "Four of five.", 0.07, SESSION, "claude-opus-5-5", 36_210, 2_190, 41_000
    )
    processes.exited[pid] = 0


def test_start_chat_writes_the_thread_and_its_first_turn_waiting() -> None:
    view = start_chat(
        Folder.GENERAL,
        "ignored",
        "Why did\nexpiry days lose?",
        "opus",
        Effort.HIGH,
        SETTINGS,
        "ui",
        NOW,
    )

    thread = agent_threads_repo.find_thread(view.thread.id)
    assert thread is not None
    assert (thread.title, thread.folder, thread.subject) == (
        "Why did expiry days lose?",
        Folder.GENERAL,
        None,
    )
    [turn] = view.turns
    stored = agent_jobs_repo.find_job(turn.job.id)
    assert stored is not None
    assert (stored.kind, stored.status, stored.thread_id) == (
        AgentJobKind.CHAT,
        AgentJobStatus.PENDING,
        thread.id,
    )
    assert (stored.prompt, stored.model, stored.effort) == (
        "Why did\nexpiry days lose?",
        "opus",
        "high",
    )


def test_a_chat_about_a_strategy_needs_one_that_exists() -> None:
    strategy = create_strategy("straddle", STRADDLE, NOW)

    view = start_chat(Folder.STRATEGY, strategy.id, "Why?", None, None, SETTINGS, "ui", NOW)

    assert view.subject_name == "straddle"
    with pytest.raises(UnknownStrategyError):
        _chat(folder=Folder.STRATEGY, subject="stg_gone")
    with pytest.raises(ChatChoiceError, match="needs its id"):
        _chat(folder=Folder.STRATEGY)
    with pytest.raises(ChatChoiceError, match="continue one instead"):
        _chat(folder=Folder.REVIEW, subject=strategy.id)


def test_an_effort_the_harness_doesnt_take_is_refused() -> None:
    with pytest.raises(ChatChoiceError, match="not minimal"):
        _chat(effort=Effort.MINIMAL)  # Codex's level, not Claude Code's


def test_the_chat_lane_starts_a_turn_with_a_chat_key_and_no_resume(tmp_path: Path) -> None:
    thread_id = _chat(model="sonnet", effort=Effort.LOW)
    processes, events = _Processes(), _Events()

    start_next_chat_turn(_context(processes, events, tmp_path), NOW)

    [launch] = processes.launches
    key = authenticate(launch.api_key)
    assert key is not None and key.scope == f"chat:{thread_id}"
    assert launch.agent is None and launch.writes_notes
    assert (launch.prompt, launch.model, launch.effort) == (
        "Why did expiry days lose?",
        "sonnet",
        "low",
    )
    assert launch.resume_session is None
    assert launch.context is not None and f"agent job {launch.job_id}" in launch.context
    assert launch.events_path == agent_job_files.events_path(launch.job_id)


def test_the_first_turn_stores_the_session_and_the_next_resumes_it(tmp_path: Path) -> None:
    thread_id = _chat()
    processes, events = _Processes(), _Events()
    context = _context(processes, events, tmp_path)
    start_next_chat_turn(context, NOW)
    first = processes.launches[0].job_id

    _answer(processes, 1001, first)
    watch_jobs(context, NOW + timedelta(seconds=41))

    thread = agent_threads_repo.find_thread(thread_id)
    assert thread is not None and thread.session_id == SESSION
    ended = agent_jobs_repo.find_job(first)
    assert ended is not None
    assert (ended.model_used, ended.input_tokens, ended.output_tokens, ended.duration_ms) == (
        "claude-opus-5-5",
        36_210,
        2_190,
        41_000,
    )
    assert authenticate(processes.launches[0].api_key) is None  # revoked as it ended

    send_message(
        thread_id, "And on other days?", None, None, SETTINGS, "ui", NOW + timedelta(minutes=1)
    )
    start_next_chat_turn(context, NOW + timedelta(minutes=1))

    assert processes.launches[1].resume_session == SESSION
    assert processes.launches[1].prompt == "And on other days?"


def test_a_thread_reads_each_turns_steps_from_its_event_stream(tmp_path: Path) -> None:
    thread_id = _chat()
    processes, events = _Processes(), _Events()
    context = _context(processes, events, tmp_path)
    start_next_chat_turn(context, NOW)
    _answer(processes, 1001, processes.launches[0].job_id)
    watch_jobs(context, NOW)

    view = read_thread(thread_id)

    [turn] = view.turns
    assert [s.kind for s in turn.steps][-1] is StepKind.TEXT
    assert turn.steps[1].tool == "get_strategy_runs"
    assert not turn.steps_truncated
    [summary] = list_threads()
    assert summary.thread.id == thread_id and summary.turns[0].steps == []


def test_a_message_needs_room_to_wait_and_a_session(tmp_path: Path) -> None:
    thread_id = _chat()

    with pytest.raises(QueueFullError):  # the first message still waits
        send_message(thread_id, "again", None, None, SETTINGS, "ui", NOW)
    with pytest.raises(UnknownThreadError):
        send_message("thr_nope", "hi", None, None, SETTINGS, "ui", NOW)

    processes, events = _Processes(), _Events()
    context = _context(processes, events, tmp_path)
    processes.fail_start = True
    start_next_chat_turn(context, NOW)  # never reached the agent: no session

    with pytest.raises(ThreadClosedError, match="start a new chat"):
        send_message(thread_id, "again", None, None, SETTINGS, "ui", NOW)


def test_a_chat_turn_runs_while_a_review_runs(tmp_path: Path) -> None:
    review = start_review(create_strategy("straddle", STRADDLE, NOW).id, SETTINGS, "ui", NOW)
    _chat()
    processes, events = _Processes(), _Events()
    context = _context(processes, events, tmp_path)

    start_next_job(context, NOW)
    start_next_chat_turn(context, NOW)

    assert len(processes.launches) == 2
    assert processes.launches[0].job_id == review.id
    assert processes.launches[1].agent is None


def test_at_most_two_chat_turns_run_and_one_per_thread(tmp_path: Path) -> None:
    for n in range(3):
        _chat(f"question {n}")
    processes, events = _Processes(), _Events()
    context = _context(processes, events, tmp_path)

    for _ in range(3):
        start_next_chat_turn(context, NOW)

    assert [launch.prompt for launch in processes.launches] == ["question 0", "question 1"]
    processes.exited[1001] = 0
    watch_jobs(context, NOW)
    start_next_chat_turn(context, NOW)
    assert processes.launches[-1].prompt == "question 2"


def test_chats_dont_count_against_the_days_cap_or_show_as_jobs(tmp_path: Path) -> None:
    settings = replace(SETTINGS, jobs_per_day=1)
    processes, events = _Processes(), _Events()
    context = replace(_context(processes, events, tmp_path), settings=settings)
    for n in range(3):
        _chat(f"q{n}")
        start_next_chat_turn(context, NOW)
        processes.exited[1001 + n] = 0
        watch_jobs(context, NOW)
    review = start_review(create_strategy("straddle", STRADDLE, NOW).id, settings, "ui", NOW)

    start_next_job(context, NOW)

    assert processes.launches[-1].job_id == review.id
    assert [job.id for job in get_agent_jobs(10, None)] == [review.id]


def test_a_restart_ends_a_running_turn_lost_and_keeps_the_thread(tmp_path: Path) -> None:
    thread_id = _chat()
    processes, events = _Processes(), _Events()
    context = _context(processes, events, tmp_path)
    start_next_chat_turn(context, NOW)

    recover_jobs(context, NOW + timedelta(minutes=1))

    ended = agent_jobs_repo.find_job(processes.launches[0].job_id)
    assert ended is not None and ended.end_reason is AgentJobEndReason.LOST
    assert agent_threads_repo.find_thread(thread_id) is not None


def test_pruning_keeps_every_turn_of_a_live_chat(tmp_path: Path) -> None:
    thread_id = _chat()
    processes, events = _Processes(), _Events()
    context = _context(processes, events, tmp_path)
    start_next_chat_turn(context, NOW)
    turn = processes.launches[0].job_id
    _answer(processes, 1001, turn)
    watch_jobs(context, NOW)
    agent_job_files.events_path("job_old").write_text("{}")

    send_message(thread_id, "more", None, None, SETTINGS, "ui", NOW)
    start_next_chat_turn(context, NOW)  # pruning runs as a job starts

    assert agent_job_files.events_path(turn).exists()
    assert not agent_job_files.events_path("job_old").exists()


def test_stop_ends_a_waiting_message_at_once_and_asks_a_running_one(tmp_path: Path) -> None:
    from openticker.use_cases.agents.threads import NothingToStopError, stop_thread

    thread_id = _chat()
    events = _Events()
    stopped = stop_thread(thread_id, events, "ui", NOW)
    assert (stopped.status, stopped.end_reason) == (AgentJobStatus.ENDED, AgentJobEndReason.STOPPED)
    with pytest.raises(NothingToStopError):
        stop_thread(thread_id, events, "ui", NOW)

    running_id = _chat("again")
    processes = _Processes()
    context = _context(processes, events, tmp_path)
    start_next_chat_turn(context, NOW)
    asked = stop_thread(running_id, events, "ui", NOW)
    assert asked.status is AgentJobStatus.STOPPING
    watch_jobs(context, NOW)
    assert processes.stopped == [(1001, False)]  # SIGTERM; SIGKILL after the grace
