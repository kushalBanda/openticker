"""Chats with the user's coding agent (ADR 40 in docs/adr), from the web app.

A chat is a thread; each message in it is an agent job of kind `chat`, which
the daemon runs in its chat lane (use_cases/agents/supervise.py): one process
of the user's Claude Code or Codex per message, resuming the conversation
the thread's first message began. What the agent did on the way to its
answer is read from that job's event stream, never stored twice.
"""

from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from typing import Literal

from sqlalchemy.orm import Session

from openticker.core.agents import transcript
from openticker.core.agents.choices import (
    Effort,
    RunChoice,
    check_choice,
    folder_kind,
    resolve,
    run_choice,
)
from openticker.core.agents.jobs import (
    AgentJob,
    AgentJobEndReason,
    AgentJobError,
    AgentJobKind,
    AgentJobStatus,
    AgentSettings,
    Harness,
    debrief_prompt,
    review_prompt,
)
from openticker.core.agents.threads import (
    MAX_QUEUED,
    Access,
    AgentThread,
    Folder,
    chat_title,
    chat_triggered_by,
    snippet,
)
from openticker.core.agents.transcript import Step
from openticker.events.bus import EventPublisher
from openticker.events.types import AgentChatDeleted, AgentChatStarted
from openticker.storage import agent_job_files
from openticker.storage.sqlite import agent_jobs_repo, agent_threads_repo
from openticker.storage.sqlite.audit_repo import AuditEntry, list_audit
from openticker.storage.sqlite.scripts_repo import find_script
from openticker.storage.sqlite.strategies_repo import find_strategy, write_transaction
from openticker.use_cases.agents.manage import stop_agent_job
from openticker.use_cases.api_keys import CHAT_READ_SCOPE_PREFIX, CHAT_SCOPE_PREFIX
from openticker.use_cases.scripts.manage import UnknownScriptError
from openticker.use_cases.strategies.define import UnknownStrategyError

# A turn's steps in one read (ADR 8 in docs/adr): its last ones.
MAX_STEPS_PER_TURN = 200
RECENT_THREADS = 20


class UnknownThreadError(LookupError):
    pass


class ThreadBusyError(Exception):
    """The agent is still on the last message."""


class ThreadClosedError(Exception):
    """The chat can't be continued: there's no conversation to resume."""


class QueueFullError(Exception):
    """One message already waits behind the agent's turn: edit it."""


class TurnStartedError(Exception):
    """Too late: the agent already took this message, or it no longer waits."""


class NothingToStopError(Exception):
    """The agent isn't on any message of this chat."""


class ChatChoiceError(ValueError):
    """A model or effort the chat's harness doesn't take, or a folder a chat can't start in."""


@dataclass(frozen=True)
class Turn:
    job: AgentJob
    steps: list[Step]
    steps_truncated: bool = False


@dataclass(frozen=True)
class ThreadView:
    thread: AgentThread
    subject_name: str | None  # the strategy's or script's name; None when deleted
    turns: list[Turn]


def start_chat(
    folder: Folder,
    subject: str | None,
    message: str,
    model: str | None,
    effort: Effort | None,
    settings: AgentSettings,
    triggered_by: str,
    now: datetime,
    harness: Harness | None = None,
    events: EventPublisher | None = None,
    access: Access = Access.TRADE,
) -> ThreadView:
    """A new chat and its first message, waiting for the daemon. What the
    message doesn't choose comes from the folder's default (Settings); the
    harness and what the agent may do (`access`) are the chat's from then on."""
    if folder in (Folder.REVIEW, Folder.DEBRIEF):
        raise ChatChoiceError(f"a chat can't be started in {folder}s: continue one instead")
    if folder is Folder.GENERAL:
        subject = None
    elif not subject:
        raise ChatChoiceError(f"a chat about a {folder} needs its id as the subject")
    elif folder is Folder.STRATEGY and find_strategy(subject) is None:
        raise UnknownStrategyError(f"no strategy {subject}")
    elif folder is Folder.SCRIPT and find_script(subject) is None:
        raise UnknownScriptError(f"no script {subject}")
    choice = _choice(
        RunChoice(harness=harness, model=model, effort=effort),
        run_choice(settings, folder_kind(folder)),
        settings,
    )
    assert choice.harness is not None
    with write_transaction() as session:
        thread = agent_threads_repo.add_thread(
            session, folder, subject, choice.harness, chat_title(message), now, access=access
        )
        job = _add_turn(session, thread, message, choice, triggered_by, now)
    if events is not None:
        events.publish(
            AgentChatStarted(
                thread_id=thread.id,
                title=thread.title,
                folder=thread.folder.value,
                subject=thread.subject,
                harness=thread.harness.value,
                triggered_by=triggered_by,
            )
        )
    return ThreadView(thread, subject_name(thread), [Turn(job, [])])


def send_message(
    thread_id: str,
    message: str,
    model: str | None,
    effort: Effort | None,
    settings: AgentSettings,
    triggered_by: str,
    now: datetime,
) -> Turn:
    """The chat's next message, waiting for the daemon. Sent while the agent
    is still on the last one, it waits its turn: one at a time (ADR 40).
    Refused when there's no conversation to resume and no turn running that
    may still give one."""
    with write_transaction() as session:
        thread = agent_threads_repo.find_thread(thread_id, session)
        if thread is None or thread.deleted_at is not None:
            raise UnknownThreadError(f"no chat {thread_id}")
        turns = agent_jobs_repo.turns_of(thread_id, session)
        waiting = [turn for turn in turns if turn.status is AgentJobStatus.PENDING]
        if len(waiting) >= MAX_QUEUED:
            raise QueueFullError("one message already waits for the agent: edit it instead")
        running = any(turn.status is AgentJobStatus.RUNNING for turn in turns)
        if any(turn.status is AgentJobStatus.STOPPING for turn in turns):
            raise ThreadBusyError("the agent is stopping: send once it has")
        if thread.session_id is None and not running:
            raise ThreadClosedError(
                "the agent has no conversation to continue here (its first message never "
                "reached it, or its session is gone): start a new chat"
            )
        choice = _choice(
            RunChoice(harness=thread.harness, model=model, effort=effort),
            run_choice(settings, folder_kind(thread.folder)),
            settings,
        )
        job = _add_turn(session, thread, message, choice, triggered_by, now)
        agent_threads_repo.touch(session, thread_id, now)
        agent_threads_repo.mark_read(session, thread_id, now)  # the user is in it
        if thread.archived_at is not None:  # talking to it again brings it back
            agent_threads_repo.set_archived(session, thread_id, None)
    return Turn(job, [])


def stop_thread(
    thread_id: str, events: EventPublisher, triggered_by: str, now: datetime
) -> AgentJob:
    """Stops the turn the agent is on: openticker-serve stops it (SIGTERM,
    then SIGKILL after the grace). A message waiting behind it still runs;
    with none running, the waiting one never starts."""
    thread = agent_threads_repo.find_thread(thread_id)
    if thread is None or thread.deleted_at is not None:
        raise UnknownThreadError(f"no chat {thread_id}")
    live = [t for t in agent_jobs_repo.turns_of(thread_id) if t.status is not AgentJobStatus.ENDED]
    if not live:
        raise NothingToStopError("the agent isn't working on this chat")
    running = [t for t in live if t.status is not AgentJobStatus.PENDING]
    return stop_agent_job((running or live)[0].id, events, triggered_by, now)


def edit_queued(thread_id: str, job_id: str, message: str) -> Turn:
    """Rewrites the message waiting for the agent, until the agent takes it."""
    text = message.strip()
    if not text:
        raise ChatChoiceError("a message can't be blank")
    with write_transaction() as session:
        job = _queued(session, thread_id, job_id)
        if not agent_jobs_repo.set_prompt(session, job.id, text):
            raise TurnStartedError("the agent already took this message")
    return Turn(replace(job, prompt=text), [])


def remove_queued(
    thread_id: str, job_id: str, events: EventPublisher, triggered_by: str, now: datetime
) -> AgentJob:
    """Takes back the message waiting for the agent: it ends stopped, never started."""
    with write_transaction() as session:
        job = _queued(session, thread_id, job_id)
    return stop_agent_job(job.id, events, triggered_by, now)


def _queued(session: Session, thread_id: str, job_id: str) -> AgentJob:
    thread = agent_threads_repo.find_thread(thread_id, session)
    if thread is None or thread.deleted_at is not None:
        raise UnknownThreadError(f"no chat {thread_id}")
    job = next((t for t in agent_jobs_repo.turns_of(thread_id, session) if t.id == job_id), None)
    if job is None:
        raise UnknownThreadError(f"no message {job_id} in chat {thread_id}")
    if job.status is not AgentJobStatus.PENDING:
        raise TurnStartedError("the agent already took this message, or it no longer waits")
    return job


def delete_thread(thread_id: str, events: EventPublisher, triggered_by: str, now: datetime) -> None:
    """Takes a chat out of the web app. Its turns stay as agent jobs, and its
    files go with the next prune. Refused while the agent is on it."""
    with write_transaction() as session:
        thread = agent_threads_repo.find_thread(thread_id, session)
        if thread is None or thread.deleted_at is not None:
            raise UnknownThreadError(f"no chat {thread_id}")
        turns = agent_jobs_repo.turns_of(thread_id, session)
        if any(turn.status is not AgentJobStatus.ENDED for turn in turns):
            raise ThreadBusyError("the agent is still working in this chat: stop it first")
        agent_threads_repo.mark_deleted(session, thread_id, now)
    events.publish(AgentChatDeleted(thread_id, thread.title, triggered_by))


def recorded_as(scope: str) -> str:
    """Who a key's calls are recorded as (ADR 35): a chat's key, read-only or
    not, as its chat with its harness ("chat:claude:thr_…"), any other agent
    key as its scope."""
    prefix = next(
        (p for p in (CHAT_SCOPE_PREFIX, CHAT_READ_SCOPE_PREFIX) if scope.startswith(p)), None
    )
    if prefix is None:
        return scope
    thread = agent_threads_repo.find_thread(scope.removeprefix(prefix))
    return chat_triggered_by(thread.harness, thread.id) if thread else scope


def update_thread(
    thread_id: str,
    now: datetime,
    *,
    title: str | None = None,
    pinned: bool | None = None,
    archived: bool | None = None,
    read: bool | None = None,
) -> AgentThread:
    """The user's own handling of a chat: renamed, pinned on top of the
    list, archived out of it (not while the agent works in it), or seen."""
    with write_transaction() as session:
        thread = agent_threads_repo.find_thread(thread_id, session)
        if thread is None or thread.deleted_at is not None:
            raise UnknownThreadError(f"no chat {thread_id}")
        if title is not None:
            if not title.strip():
                raise ChatChoiceError("a chat's title can't be blank")
            agent_threads_repo.set_title(session, thread_id, chat_title(title))
        if pinned is not None and pinned != (thread.pinned_at is not None):
            agent_threads_repo.set_pinned(session, thread_id, now if pinned else None)
        if archived is not None and archived != (thread.archived_at is not None):
            turns = agent_jobs_repo.turns_of(thread_id, session)
            if archived and any(t.status is not AgentJobStatus.ENDED for t in turns):
                raise ThreadBusyError("the agent is still working in this chat: stop it first")
            agent_threads_repo.set_archived(session, thread_id, now if archived else None)
        if read:
            agent_threads_repo.mark_read(session, thread_id, now)
        updated = agent_threads_repo.find_thread(thread_id, session)
    assert updated is not None
    return updated


# What a chat changed, in one read (ADR 8): its latest entries.
MAX_CHANGES = 200


def thread_changes(thread_id: str, job_id: str | None = None) -> list[AuditEntry]:
    """What the agent changed on the desk from this chat, most recent first:
    the audit entries recorded as the chat (ADR 35), in the turn `job_id`
    when given. Never what the user did by hand meanwhile."""
    thread = agent_threads_repo.find_thread(thread_id)
    if thread is None or thread.deleted_at is not None:
        raise UnknownThreadError(f"no chat {thread_id}")
    since, until = thread.created_at, None
    if job_id is not None:
        job = next((t for t in agent_jobs_repo.turns_of(thread_id) if t.id == job_id), None)
        if job is None:
            raise UnknownThreadError(f"no turn {job_id} in chat {thread_id}")
        if job.started_at is None:
            return []
        since, until = job.started_at, job.ended_at
    return list_audit(
        MAX_CHANGES,
        triggered_by=chat_triggered_by(thread.harness, thread.id),
        since=since,
        until=until,
    )


def read_thread(thread_id: str) -> ThreadView:
    """A chat with every turn and what the agent did in each."""
    thread = agent_threads_repo.find_thread(thread_id)
    if thread is None or thread.deleted_at is not None:
        raise UnknownThreadError(f"no chat {thread_id}")
    turns = [_turn(job) for job in _shown(agent_jobs_repo.turns_of(thread_id))]
    return ThreadView(thread, subject_name(thread), turns)


def list_threads(
    folder: Folder | None = None, subject: str | None = None, limit: int = RECENT_THREADS
) -> list[ThreadView]:
    """The chats, most recently active first, their turns without steps. A
    strategy's folder holds its reviews too. Recent chats leave out the
    pinned ones, which are listed on their own."""
    if folder is None:
        threads = agent_threads_repo.recent_threads(limit)
    else:
        folders = {folder, Folder.REVIEW} if folder is Folder.STRATEGY and subject else {folder}
        threads = agent_threads_repo.threads_in(folders, subject, limit)
    return _summaries(threads)


def pinned_threads() -> list[ThreadView]:
    """The chats the user pinned, the latest pinned first, turns without steps."""
    return _summaries(agent_threads_repo.pinned_threads())


def _summaries(threads: Iterable[AgentThread]) -> list[ThreadView]:
    return [
        ThreadView(
            thread,
            subject_name(thread),
            [Turn(_asked(job), []) for job in _shown(agent_jobs_repo.turns_of(thread.id))],
        )
        for thread in threads
    ]


def _shown(jobs: list[AgentJob]) -> list[AgentJob]:
    """A chat's turns less the follow-ups taken back before the agent saw them."""
    return [
        job
        for i, job in enumerate(jobs)
        if i == 0
        or not (
            job.kind is AgentJobKind.CHAT
            and job.started_at is None
            and job.end_reason is AgentJobEndReason.STOPPED
        )
    ]


class SearchKind(StrEnum):
    CHATS = "chats"  # General, strategies' and scripts' chats
    REVIEWS = "reviews"
    DEBRIEFS = "debriefs"


_SEARCHED: dict[SearchKind, frozenset[Folder]] = {
    SearchKind.CHATS: frozenset({Folder.GENERAL, Folder.STRATEGY, Folder.SCRIPT}),
    SearchKind.REVIEWS: frozenset({Folder.REVIEW}),
    SearchKind.DEBRIEFS: frozenset({Folder.DEBRIEF}),
}


@dataclass(frozen=True)
class ThreadHit:
    view: ThreadView  # turns without steps
    matched: Literal["title", "message", "answer"]
    snippet: str  # around the first match
    at: datetime


def search_threads(
    query: str, kind: SearchKind | None = None, archived: bool = False, limit: int = 20
) -> list[ThreadHit]:
    """Chats, reviews and debriefs whose title, messages or answers hold
    `query`, the most recently active first; the archived ones on their own."""
    hits = agent_threads_repo.search(
        query.strip(), _SEARCHED[kind] if kind else None, archived, limit
    )
    views = _summaries(hit.thread for hit in hits)
    return [
        ThreadHit(view, hit.matched, snippet(hit.text, query.strip()), hit.at)
        for view, hit in zip(views, hits, strict=True)
    ]


@dataclass(frozen=True)
class FolderCount:
    folder: Folder
    subject: str | None  # a strategy's or script's id; None for the folder as a whole
    subject_name: str | None
    threads: int


def folder_counts() -> list[FolderCount]:
    """How many chats each folder holds: General, Reviews and Debriefs as a
    whole, Strategies and Scripts by what they're about. A strategy's count
    takes in its reviews."""
    totals: dict[tuple[Folder, str | None], int] = {}
    for folder, subject, n in agent_threads_repo.counts():
        keys: list[tuple[Folder, str | None]] = [(folder, None)]
        if folder in (Folder.STRATEGY, Folder.SCRIPT) and subject:
            keys = [(folder, subject)]
        elif folder is Folder.REVIEW and subject:
            keys.append((Folder.STRATEGY, subject))
        for key in keys:
            totals[key] = totals.get(key, 0) + n
    return [
        FolderCount(folder, subject, _name_of(folder, subject), n)
        for (folder, subject), n in sorted(
            totals.items(), key=lambda item: (item[0][0], item[0][1] or "")
        )
    ]


def _add_turn(
    session: Session,
    thread: AgentThread,
    message: str,
    choice: RunChoice,
    triggered_by: str,
    now: datetime,
) -> AgentJob:
    return agent_jobs_repo.add_job(
        session,
        AgentJobKind.CHAT,
        None,
        thread.harness,
        triggered_by,
        now,
        thread_id=thread.id,
        prompt=message,
        model=choice.model,
        effort=choice.effort.value if choice.effort else None,
    )


def _choice(override: RunChoice, folder: RunChoice, settings: AgentSettings) -> RunChoice:
    """What the message runs with: its own choice, refused when the harness
    doesn't take it, then the folder's default."""
    try:
        check_choice(override, override.harness or folder.harness or settings.harness)
    except AgentJobError as exc:
        raise ChatChoiceError(str(exc)) from None
    return resolve(override, folder, default_harness=settings.harness)


def _turn(job: AgentJob) -> Turn:
    steps = transcript.read_steps(job.harness, agent_job_files.read_events(job.id))
    return Turn(_asked(job), *_last(steps))


def _last(steps: Iterable[Step]) -> tuple[list[Step], bool]:
    kept = list(steps)
    if len(kept) <= MAX_STEPS_PER_TURN:
        return kept, False
    return kept[-MAX_STEPS_PER_TURN:], True


def _asked(job: AgentJob) -> AgentJob:
    """A review or debrief keeps no prompt of its own: what it was asked is
    rebuilt from its kind, without the job id the daemon adds for itself."""
    if job.prompt is not None:
        return job
    if job.kind is AgentJobKind.REVIEW and job.strategy_id:
        stored = find_strategy(job.strategy_id)
        name = stored.name if stored else "(since deleted)"
        prompt = review_prompt(name, job.strategy_id, job.id, job.trigger)
    elif job.kind is AgentJobKind.DEBRIEF and job.subject:
        prompt = debrief_prompt(job.subject, job.id, job.trigger)
    else:
        return job
    return replace(job, prompt=prompt.removesuffix(f" (OpenTicker agent job {job.id})"))


def _name_of(folder: Folder, subject: str | None) -> str | None:
    if subject is None:
        return None
    if folder in (Folder.STRATEGY, Folder.REVIEW):
        stored = find_strategy(subject)
        return stored.name if stored else None
    if folder is Folder.SCRIPT:
        script = find_script(subject)
        return script.name if script else None
    return None


def subject_name(thread: AgentThread) -> str | None:
    """The name of what a chat is about: its strategy's or script's; None when deleted."""
    return _name_of(thread.folder, thread.subject)
