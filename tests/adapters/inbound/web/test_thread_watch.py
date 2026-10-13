from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from openticker.adapters.inbound.web.models import ThreadStepsMessage, ThreadTurnMessage
from openticker.adapters.inbound.web.thread_watch import ThreadWatch
from openticker.core.agents.jobs import AgentJobEndReason, AgentSettings
from openticker.core.agents.threads import Folder
from openticker.storage import agent_job_files
from openticker.storage.sqlite import agent_jobs_repo, agent_threads_repo
from openticker.storage.sqlite.strategies_repo import write_transaction
from openticker.use_cases.agents.threads import send_message, start_chat

NOW = datetime(2026, 9, 22, 4, 0, tzinfo=UTC)
LINES = (
    (Path(__file__).parents[3] / "fixtures" / "transcripts" / "claude_turn.jsonl")
    .read_text()
    .splitlines(keepends=True)
)


def _running_chat() -> tuple[str, str]:
    view = start_chat(Folder.GENERAL, None, "hi", None, None, AgentSettings(), "ui", NOW)
    job_id = view.turns[0].job.id
    with write_transaction() as session:
        agent_jobs_repo.mark_running(session, job_id, 4242, NOW)
    return view.thread.id, job_id


def _write(job_id: str, text: str) -> None:
    with agent_job_files.events_path(job_id).open("a") as events:
        events.write(text)


def _steps(messages: Sequence[object]) -> list[ThreadStepsMessage]:
    return [m for m in messages if isinstance(m, ThreadStepsMessage)]


def test_sends_only_new_steps_and_resends_a_call_once_its_result_arrives() -> None:
    thread_id, job_id = _running_chat()
    watch = ThreadWatch(thread_id)
    assert watch.poll() == []  # nothing written yet

    _write(job_id, "".join(LINES[:4]))  # hook, init, thinking, the call
    [first] = _steps(watch.poll())
    assert (first.from_index, [s.kind for s in first.steps]) == (0, ["thinking", "tool"])
    assert first.steps[1].result is None

    assert watch.poll() == []  # nothing new
    _write(job_id, "".join(LINES[4:6]))  # a rate-limit line, the call's result
    [second] = _steps(watch.poll())
    assert second.from_index == 1  # the call again, now with its result
    assert second.steps[0].result is not None


def test_holds_a_partial_line_until_it_is_complete() -> None:
    thread_id, job_id = _running_chat()
    watch = ThreadWatch(thread_id)
    watch.poll()
    thinking = LINES[2]

    _write(job_id, LINES[1] + thinking[:30])
    assert _steps(watch.poll()) == []
    _write(job_id, thinking[30:])
    [message] = _steps(watch.poll())
    assert [s.kind for s in message.steps] == ["thinking"]


def test_a_turn_ending_sends_its_last_steps_then_the_turn() -> None:
    thread_id, job_id = _running_chat()
    watch = ThreadWatch(thread_id)
    watch.poll()

    _write(job_id, "".join(LINES))
    with write_transaction() as session:
        agent_jobs_repo.end_job(
            session, job_id, AgentJobEndReason.FINISHED, "exited with code 0", NOW + timedelta(1)
        )
    messages = watch.poll()

    assert isinstance(messages[0], ThreadStepsMessage)
    assert isinstance(messages[-1], ThreadTurnMessage)
    assert messages[-1].turn.status == "ended"
    assert watch.poll() == []  # an ended turn isn't read again


def test_a_new_message_is_sent_as_a_turn() -> None:
    thread_id, job_id = _running_chat()
    watch = ThreadWatch(thread_id)
    watch.poll()
    with write_transaction() as session:
        agent_jobs_repo.end_job(session, job_id, AgentJobEndReason.FINISHED, "", NOW)
    watch.poll()
    with write_transaction() as session:
        agent_threads_repo.set_session(session, thread_id, "s")
    turn = send_message(thread_id, "more", None, None, AgentSettings(), "ui", NOW)

    [message] = watch.poll()
    assert isinstance(message, ThreadTurnMessage)
    assert (message.turn.job_id, message.turn.status) == (turn.job.id, "pending")
