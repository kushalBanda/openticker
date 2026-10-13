"""Reviews and debriefs as chats (ADR 40): each opens its thread in the
transaction that queues it, shows what it was asked as its first message,
files under its strategy, and once ended continues as a chat that resumes
its session with a chat key."""

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from openticker.core.agents.jobs import AgentJobEndReason, AgentJobKind, AgentJobStatus, Harness
from openticker.core.agents.threads import (
    READ_ONLY_LINE,
    Access,
    Folder,
    chat_triggered_by,
    is_unread,
)
from openticker.events.types import AgentJobEnded
from openticker.ports.agent_job_port import AgentOutcome
from openticker.storage import agent_job_files
from openticker.storage.sqlite import agent_jobs_repo, agent_threads_repo
from openticker.storage.sqlite.audit_repo import write_audit
from openticker.storage.sqlite.strategies_repo import write_transaction
from openticker.use_cases.agents import supervise
from openticker.use_cases.agents.manage import AgentJobBusyError, start_review
from openticker.use_cases.agents.supervise import (
    recover_jobs,
    start_next_chat_turn,
    start_next_job,
    watch_jobs,
)
from openticker.use_cases.agents.threads import (
    ChatChoiceError,
    QueueFullError,
    SearchKind,
    ThreadBusyError,
    ThreadClosedError,
    TurnStartedError,
    UnknownThreadError,
    edit_queued,
    folder_counts,
    list_threads,
    pinned_threads,
    read_thread,
    recorded_as,
    remove_queued,
    search_threads,
    send_message,
    start_chat,
    stop_thread,
    thread_changes,
    update_thread,
)
from openticker.use_cases.api_keys import authenticate
from openticker.use_cases.brain.debrief import start_debrief
from tests.fixtures.brain_day import monday
from tests.fixtures.pnl_desk import MONDAY
from tests.fixtures.strategies import list_nifty_market
from tests.use_cases.agents.test_agent_jobs import (
    NOW,
    SETTINGS,
    _context,
    _Events,
    _Processes,
    _strategy,
)
from tests.use_cases.agents.test_debrief_jobs import AFTER_CLOSE, CALENDAR


@pytest.fixture(autouse=True)
def _market() -> None:
    list_nifty_market()


def test_a_review_opens_its_thread_when_queued_and_a_refused_one_opens_none() -> None:
    strategy_id = _strategy()

    job = start_review(strategy_id, SETTINGS, "ui", NOW)

    assert job.thread_id is not None
    thread = agent_threads_repo.find_thread(job.thread_id)
    assert thread is not None
    assert (thread.folder, thread.subject, thread.origin_job_id) == (
        Folder.REVIEW,
        strategy_id,
        job.id,
    )
    assert (thread.title, thread.harness, thread.session_id) == (
        "Review of straddle",
        job.harness,
        None,
    )
    with pytest.raises(AgentJobBusyError):
        start_review(strategy_id, SETTINGS, "ui", NOW)
    assert len(list_threads()) == 1


def test_a_debrief_opens_its_thread_too() -> None:
    monday()

    job = start_debrief(MONDAY, SETTINGS, "ui", AFTER_CLOSE, CALENDAR)

    assert job.thread_id is not None
    thread = agent_threads_repo.find_thread(job.thread_id)
    assert thread is not None
    assert (thread.folder, thread.subject, thread.title) == (
        Folder.DEBRIEF,
        "2026-09-21",
        "Debrief of Mon 21 Sep",
    )


def test_its_first_message_is_what_it_was_asked_without_the_job_id() -> None:
    job = start_review(_strategy(), SETTINGS, "schedule: 10 runs", NOW)
    assert job.thread_id is not None

    [turn] = read_thread(job.thread_id).turns

    assert turn.job.kind is AgentJobKind.REVIEW and turn.job.prompt is not None
    assert turn.job.prompt.startswith("Review the OpenTicker strategy 'straddle'")
    assert "It is due on its review schedule: 10 runs." in turn.job.prompt
    assert "agent job" not in turn.job.prompt


def test_an_ended_review_continues_as_a_chat_resuming_its_session(tmp_path: Path) -> None:
    strategy_id = _strategy()
    job = start_review(strategy_id, SETTINGS, "ui", NOW)
    assert job.thread_id is not None
    processes, events = _Processes(), _Events()
    processes.answer = AgentOutcome("keep", 0.42, "sess-review", "claude-opus-5-5")
    context = _context(processes, events, tmp_path)
    start_next_job(context, NOW)
    turn = send_message(job.thread_id, "Why keep?", None, None, SETTINGS, "ui", NOW)
    start_next_chat_turn(context, NOW + timedelta(minutes=1))  # waits for the review
    assert len(processes.launches) == 1

    processes.exited[1001] = 0
    watch_jobs(context, NOW + timedelta(minutes=2))
    start_next_chat_turn(context, NOW + timedelta(minutes=3))

    assert turn.job.kind is AgentJobKind.CHAT and turn.job.thread_id == job.thread_id
    review, chat = processes.launches
    assert (review.agent, review.resume_session) == ("reviewer", None)
    assert (chat.agent, chat.resume_session) == (None, "sess-review")
    assert chat.context is not None and f"strategy 'straddle' ({strategy_id})" in chat.context
    key = authenticate(chat.api_key)
    assert key is not None and key.scope == f"chat:{job.thread_id}"
    turns = read_thread(job.thread_id).turns
    assert [t.job.kind for t in turns] == [AgentJobKind.REVIEW, AgentJobKind.CHAT]
    assert turns[1].job.status is AgentJobStatus.RUNNING


def test_a_strategys_folder_holds_its_chats_and_reviews_and_counts_them() -> None:
    straddle, other = _strategy(), _strategy("other")
    review = start_review(straddle, SETTINGS, "ui", NOW)
    start_review(other, SETTINGS, "ui", NOW)
    chat = start_chat(Folder.STRATEGY, straddle, "Why?", None, None, SETTINGS, "ui", NOW)
    start_chat(Folder.GENERAL, None, "Hi", None, None, SETTINGS, "ui", NOW)

    inside = list_threads(Folder.STRATEGY, straddle)

    assert {view.thread.id for view in inside} == {review.thread_id, chat.thread.id}
    counts = {(c.folder, c.subject): (c.subject_name, c.threads) for c in folder_counts()}
    assert counts == {
        (Folder.GENERAL, None): (None, 1),
        (Folder.REVIEW, None): (None, 2),
        (Folder.STRATEGY, straddle): ("straddle", 2),
        (Folder.STRATEGY, other): ("other", 1),
    }


def test_prune_keeps_a_review_threads_output_and_drops_an_old_jobs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(supervise, "KEPT_JOBS", 0)  # only threads' jobs are kept
    legacy = _strategy("old")
    with write_transaction() as session:  # from before threads: none of its own
        old = agent_jobs_repo.add_job(
            session, AgentJobKind.REVIEW, legacy, Harness.CLAUDE, "ui", NOW
        )
    review = start_review(_strategy(), SETTINGS, "ui", NOW)
    for job in (old, review):
        agent_job_files.events_path(job.id).write_text("{}\n")

    start_next_job(_context(_Processes(), _Events(), tmp_path), NOW)  # prunes as it starts

    assert agent_job_files.events_path(review.id).exists()
    assert not agent_job_files.events_path(old.id).exists()


def test_a_chat_whose_conversation_is_gone_can_only_start_afresh(tmp_path: Path) -> None:
    view = start_chat(Folder.GENERAL, None, "Hi", None, None, SETTINGS, "ui", NOW)
    processes, events = _Processes(), _Events()
    processes.answer = AgentOutcome("hello", None, "sess-1")
    context = _context(processes, events, tmp_path)
    start_next_chat_turn(context, NOW)
    processes.exited[1001] = 0
    watch_jobs(context, NOW)
    send_message(view.thread.id, "And?", None, None, SETTINGS, "ui", NOW)
    gone = "No conversation found with session ID: sess-1"
    processes.answer = AgentOutcome(gone, None, error=gone)
    start_next_chat_turn(context, NOW)
    processes.exited[1002] = 1

    watch_jobs(context, NOW)

    assert processes.launches[1].resume_session == "sess-1"
    thread = read_thread(view.thread.id)
    assert thread.thread.session_id is None
    last = thread.turns[-1].job
    assert last.end_detail is not None and "can't be resumed" in last.end_detail
    with pytest.raises(ThreadClosedError, match="start a new chat"):
        send_message(view.thread.id, "Again?", None, None, SETTINGS, "ui", NOW)


def test_a_restart_ends_a_running_chat_turn_lost_and_keeps_its_chat(tmp_path: Path) -> None:
    view = start_chat(Folder.GENERAL, None, "Hi", None, None, SETTINGS, "ui", NOW)
    processes, events = _Processes(), _Events()
    start_next_chat_turn(_context(processes, events, tmp_path), NOW)

    after = _Processes()  # a new daemon: the old process isn't one of its own
    recover_jobs(_context(after, events, tmp_path), NOW + timedelta(minutes=1))

    [turn] = read_thread(view.thread.id).turns
    assert (turn.job.status, turn.job.end_reason) == (AgentJobStatus.ENDED, AgentJobEndReason.LOST)
    assert [t.thread.id for t in list_threads()] == [view.thread.id]
    assert authenticate(processes.launches[0].api_key) is None


def test_a_pinned_chat_leaves_recents_and_keeps_its_folder_and_pin_order() -> None:
    old = start_chat(Folder.GENERAL, None, "old", None, None, SETTINGS, "ui", NOW)
    new = start_chat(Folder.GENERAL, None, "new", None, None, SETTINGS, "ui", NOW)

    update_thread(old.thread.id, NOW, pinned=True)
    update_thread(new.thread.id, NOW + timedelta(minutes=1), pinned=True)
    update_thread(new.thread.id, NOW + timedelta(minutes=2), pinned=True)  # already: unchanged

    assert [v.thread.id for v in pinned_threads()] == [new.thread.id, old.thread.id]
    assert list_threads() == []
    assert {v.thread.id for v in list_threads(Folder.GENERAL)} == {old.thread.id, new.thread.id}
    assert update_thread(old.thread.id, NOW, pinned=False).pinned_at is None
    assert [v.thread.id for v in list_threads()] == [old.thread.id]


def test_rename_archive_and_restore_a_chat() -> None:
    view = start_chat(Folder.GENERAL, None, "hi", None, None, SETTINGS, "ui", NOW)
    with write_transaction() as session:  # its turn ended: it can be archived
        agent_jobs_repo.end_job(
            session, view.turns[0].job.id, AgentJobEndReason.FINISHED, "ok", NOW
        )

    renamed = update_thread(view.thread.id, NOW, title="  Hedge plan  ")
    archived = update_thread(view.thread.id, NOW, archived=True)

    assert renamed.title == "Hedge plan"
    assert archived.archived_at == NOW
    assert list_threads() == [] and list_threads(Folder.GENERAL) == []
    assert folder_counts() == []
    assert read_thread(view.thread.id).thread.title == "Hedge plan"  # still opens
    update_thread(view.thread.id, NOW, archived=False)
    assert [v.thread.id for v in list_threads()] == [view.thread.id]
    with pytest.raises(ChatChoiceError, match="blank"):
        update_thread(view.thread.id, NOW, title="   ")


def test_a_chat_cant_be_archived_while_the_agent_works_in_it() -> None:
    view = start_chat(Folder.GENERAL, None, "hi", None, None, SETTINGS, "ui", NOW)

    with pytest.raises(ThreadBusyError):
        update_thread(view.thread.id, NOW, archived=True)


def test_a_chat_is_unread_when_a_turn_ends_after_the_user_saw_it(tmp_path: Path) -> None:
    view = start_chat(Folder.GENERAL, None, "hi", None, None, SETTINGS, "ui", NOW)
    processes, events = _Processes(), _Events()
    context = _context(processes, events, tmp_path)
    start_next_chat_turn(context, NOW)
    processes.exited[1001] = 0

    watch_jobs(context, NOW + timedelta(minutes=1))

    thread = read_thread(view.thread.id).thread
    [ended] = events.of(AgentJobEnded)
    assert isinstance(ended, AgentJobEnded)
    assert (ended.thread_id, ended.title) == (view.thread.id, "hi")
    assert is_unread(thread, NOW + timedelta(minutes=1))
    seen = update_thread(view.thread.id, NOW + timedelta(minutes=2), read=True)
    assert not is_unread(seen, NOW + timedelta(minutes=1))


def test_a_chat_from_before_read_was_recorded_counts_as_read() -> None:
    old = replace(
        start_chat(Folder.GENERAL, None, "hi", None, None, SETTINGS, "ui", NOW).thread,
        read_at=None,
    )

    assert not is_unread(old, NOW + timedelta(days=1))


def test_search_finds_chats_by_title_message_or_answer_and_the_archived_apart(
    tmp_path: Path,
) -> None:
    by_answer = start_chat(
        Folder.GENERAL, None, "Why did it lose?", None, None, SETTINGS, "ui", NOW
    )
    by_message = start_chat(
        Folder.GENERAL, None, "Is VIX_high 100%?", None, None, SETTINGS, "ui", NOW
    )
    review = start_review(_strategy(), SETTINGS, "ui", NOW)
    with write_transaction() as session:
        for view_job, answer in ((by_answer.turns[0].job.id, "When INDIA VIX opened high."),):
            agent_jobs_repo.end_job(
                session, view_job, AgentJobEndReason.FINISHED, "ok", NOW, summary=answer
            )
        agent_jobs_repo.end_job(
            session, by_message.turns[0].job.id, AgentJobEndReason.FINISHED, "ok", NOW
        )
    assert review.thread_id is not None

    found = {hit.view.thread.id: hit for hit in search_threads("vix")}
    escaped = search_threads("_high 100%")
    reviews = search_threads("straddle", SearchKind.REVIEWS)
    update_thread(by_answer.thread.id, NOW, archived=True)

    assert found[by_answer.thread.id].matched == "answer"
    assert found[by_answer.thread.id].snippet == "When INDIA VIX opened high."
    assert found[by_message.thread.id].matched == "message"
    assert [hit.view.thread.id for hit in escaped] == [by_message.thread.id]
    assert [(hit.view.thread.id, hit.matched) for hit in reviews] == [(review.thread_id, "title")]
    assert search_threads("straddle", SearchKind.CHATS) == []
    assert [hit.view.thread.id for hit in search_threads("vix")] == [by_message.thread.id]
    assert [hit.view.thread.id for hit in search_threads("vix", archived=True)] == [
        by_answer.thread.id
    ]


def test_a_message_to_an_archived_chat_brings_it_back(tmp_path: Path) -> None:
    view = start_chat(Folder.GENERAL, None, "hi", None, None, SETTINGS, "ui", NOW)
    processes = _Processes()
    processes.answer = AgentOutcome("hello", None, "sess-1")
    context = _context(processes, _Events(), tmp_path)
    start_next_chat_turn(context, NOW)
    processes.exited[1001] = 0
    watch_jobs(context, NOW)
    update_thread(view.thread.id, NOW, archived=True)

    send_message(view.thread.id, "And?", None, None, SETTINGS, "ui", NOW)

    assert read_thread(view.thread.id).thread.archived_at is None


def test_changes_are_what_this_chat_did_and_in_one_turn_only_that_turn(tmp_path: Path) -> None:
    view = start_chat(Folder.GENERAL, None, "Hedge it", None, None, SETTINGS, "ui", NOW)
    other = start_chat(Folder.GENERAL, None, "Other", None, None, SETTINGS, "ui", NOW)
    processes = _Processes()
    processes.answer = AgentOutcome("done", None, "sess-1")
    context = _context(processes, _Events(), tmp_path)
    start_next_chat_turn(context, NOW)
    as_chat = chat_triggered_by(view.thread.harness, view.thread.id)
    write_audit("OrderPlaced", NOW + timedelta(seconds=5), as_chat, '{"order_id": "o1"}')
    write_audit("OrderPlaced", NOW + timedelta(seconds=6), "ui", '{"order_id": "mine"}')
    write_audit(
        "OrderPlaced",
        NOW + timedelta(seconds=7),
        chat_triggered_by(other.thread.harness, other.thread.id),
        '{"order_id": "o2"}',
    )
    processes.exited[1001] = 0
    watch_jobs(context, NOW + timedelta(minutes=1))
    write_audit("WatchlistChanged", NOW + timedelta(minutes=2), as_chat, "{}")  # after the turn

    every = thread_changes(view.thread.id)
    in_turn = thread_changes(view.thread.id, view.turns[0].job.id)

    assert [e.event_type for e in every] == ["WatchlistChanged", "OrderPlaced"]
    assert [e.payload for e in in_turn] == ['{"order_id": "o1"}']
    assert thread_changes(other.thread.id, other.turns[0].job.id) == []  # never started
    with pytest.raises(UnknownThreadError):
        thread_changes(view.thread.id, "job_nope")


def _chat_running(
    context: supervise.AgentContext, message: str = "Hi", at: timedelta = timedelta()
) -> str:
    view = start_chat(Folder.GENERAL, None, message, None, None, SETTINGS, "ui", NOW + at)
    start_next_chat_turn(context, NOW + at)
    return view.thread.id


def test_a_message_sent_while_the_agent_works_waits_its_turn(tmp_path: Path) -> None:
    processes, events = _Processes(), _Events()
    processes.answer = AgentOutcome("hello", None, "sess-1")
    context = _context(processes, events, tmp_path)
    thread_id = _chat_running(context)  # no session yet: the first turn may still give one

    queued = send_message(thread_id, "And then?", None, None, SETTINGS, "ui", NOW)
    start_next_chat_turn(context, NOW)

    assert queued.job.status is AgentJobStatus.PENDING
    assert len(processes.launches) == 1
    processes.exited[1001] = 0
    watch_jobs(context, NOW + timedelta(minutes=1))
    start_next_chat_turn(context, NOW + timedelta(minutes=1))
    assert [launch.resume_session for launch in processes.launches] == [None, "sess-1"]
    assert read_thread(thread_id).turns[-1].job.status is AgentJobStatus.RUNNING


def test_only_one_message_waits(tmp_path: Path) -> None:
    thread_id = _chat_running(_context(_Processes(), _Events(), tmp_path))
    send_message(thread_id, "And then?", None, None, SETTINGS, "ui", NOW)

    with pytest.raises(QueueFullError, match="edit it"):
        send_message(thread_id, "And after?", None, None, SETTINGS, "ui", NOW)


def test_a_waiting_message_on_one_chat_doesnt_hold_up_another(tmp_path: Path) -> None:
    processes, events = _Processes(), _Events()
    context = _context(processes, events, tmp_path)
    busy = _chat_running(context)
    send_message(busy, "And then?", None, None, SETTINGS, "ui", NOW + timedelta(seconds=1))
    other = start_chat(
        Folder.GENERAL, None, "Other", None, None, SETTINGS, "ui", NOW + timedelta(seconds=2)
    )

    start_next_chat_turn(context, NOW + timedelta(seconds=3))

    assert [launch.prompt for launch in processes.launches] == ["Hi", "Other"]
    assert read_thread(other.thread.id).turns[0].job.status is AgentJobStatus.RUNNING
    assert read_thread(busy).turns[-1].job.status is AgentJobStatus.PENDING


def test_a_waiting_message_ends_refused_when_its_chat_lost_its_session(tmp_path: Path) -> None:
    processes, events = _Processes(), _Events()
    processes.answer = AgentOutcome("", None, error="not signed in")  # never gives a session
    context = _context(processes, events, tmp_path)
    thread_id = _chat_running(context)
    send_message(thread_id, "And then?", None, None, SETTINGS, "ui", NOW)
    processes.exited[1001] = 1
    watch_jobs(context, NOW)

    start_next_chat_turn(context, NOW)

    assert len(processes.launches) == 1
    last = read_thread(thread_id).turns[-1].job
    assert (last.status, last.end_reason) == (AgentJobStatus.ENDED, AgentJobEndReason.REFUSED)
    assert last.end_detail is not None and "can't be continued" in last.end_detail


def test_a_waiting_message_can_be_edited_or_removed_until_it_starts(tmp_path: Path) -> None:
    processes, events = _Processes(), _Events()
    processes.answer = AgentOutcome("hello", None, "sess-1")
    context = _context(processes, events, tmp_path)
    thread_id = _chat_running(context)
    queued = send_message(thread_id, "And then?", None, None, SETTINGS, "ui", NOW)

    edited = edit_queued(thread_id, queued.job.id, "  And after that?  ")
    assert edited.job.prompt == "And after that?"
    removed = remove_queued(thread_id, queued.job.id, events, "ui", NOW)
    assert (removed.status, removed.end_reason) == (
        AgentJobStatus.ENDED,
        AgentJobEndReason.STOPPED,
    )
    with pytest.raises(TurnStartedError):  # gone: nothing waits now
        edit_queued(thread_id, queued.job.id, "Too late")

    again = send_message(thread_id, "Last one", None, None, SETTINGS, "ui", NOW)
    stop_thread(thread_id, events, "ui", NOW)  # stops the running turn, not the waiting one
    first, waiting = (turn.job for turn in read_thread(thread_id).turns)  # the removed one hidden
    assert (first.status, waiting.id) == (AgentJobStatus.STOPPING, again.job.id)
    assert waiting.status is AgentJobStatus.PENDING
    processes.exited[1001] = 0
    watch_jobs(context, NOW)
    start_next_chat_turn(context, NOW)
    with pytest.raises(TurnStartedError, match="already"):
        edit_queued(thread_id, again.job.id, "Too late")
    with pytest.raises(TurnStartedError):
        remove_queued(thread_id, again.job.id, events, "ui", NOW)


def test_a_read_only_chat_runs_with_a_read_only_key_and_says_so(tmp_path: Path) -> None:
    processes, events = _Processes(), _Events()
    context = _context(processes, events, tmp_path)
    view = start_chat(
        Folder.GENERAL,
        None,
        "How am I doing?",
        None,
        None,
        SETTINGS,
        "ui",
        NOW,
        access=Access.READ,
    )

    start_next_chat_turn(context, NOW)

    [launch] = processes.launches
    key = authenticate(launch.api_key)
    assert key is not None and key.scope == f"chat-read:{view.thread.id}"
    assert launch.context is not None and READ_ONLY_LINE in launch.context
    assert recorded_as(key.scope) == chat_triggered_by(view.thread.harness, view.thread.id)
    assert read_thread(view.thread.id).thread.access is Access.READ
