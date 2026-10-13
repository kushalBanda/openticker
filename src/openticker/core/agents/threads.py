"""Chats with the user's coding agent (ADR 40 in docs/adr). A thread is one
conversation, filed in a folder: the desk in general, one strategy, one
script, or a review or debrief continued as a chat. Each message in it is an
agent job. Pure."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from openticker.core.agents.jobs import AgentJobEndReason, Harness


class Folder(StrEnum):
    GENERAL = "general"
    STRATEGY = "strategy"  # subject: the strategy's id
    SCRIPT = "script"  # subject: the script's id
    REVIEW = "review"  # subject: the reviewed strategy's id
    DEBRIEF = "debrief"  # subject: the trading date, ISO


class Access(StrEnum):
    """What a chat's agent may do on the desk, fixed at its first message."""

    READ = "read"  # read-only tools: it answers, it changes nothing
    TRADE = "trade"  # every tool a chat may use: paper trades, strategies, notes


@dataclass(frozen=True)
class AgentThread:
    id: str
    title: str
    folder: Folder
    subject: str | None
    harness: Harness  # fixed at the first message: the two can't share a conversation
    session_id: str | None  # the harness's own, from the first turn; None until then
    origin_job_id: str | None  # the review or debrief it began as
    created_at: datetime  # tz-aware UTC
    updated_at: datetime
    deleted_at: datetime | None = None
    pinned_at: datetime | None = None  # set: kept on top of the chat list
    archived_at: datetime | None = None  # set: out of the list, found by search
    read_at: datetime | None = None  # the user last saw it; None on chats from before
    access: Access = Access.TRADE


# A turn that ended this way is shown as failed; one the user stopped is not.
FAILED_ENDS = frozenset(
    {
        AgentJobEndReason.FAILED,
        AgentJobEndReason.TIMEOUT,
        AgentJobEndReason.REFUSED,
        AgentJobEndReason.START_FAILED,
        AgentJobEndReason.DAEMON_STOPPED,
        AgentJobEndReason.LOST,
    }
)


def is_unread(thread: AgentThread, last_ended_at: datetime | None) -> bool:
    """A turn ended after the user last saw the chat. A chat from before
    reading was recorded counts as read."""
    if thread.read_at is None or last_ended_at is None:
        return False
    return last_ended_at > thread.read_at


def chat_triggered_by(harness: Harness, thread_id: str) -> str:
    """Who a chat's tool calls are recorded as (ADR 35): "chat:claude:thr_…",
    shown as "Claude (chat)"."""
    return f"chat:{harness.value}:{thread_id}"


# A search result's line: this long, around the first match.
SNIPPET_CHARS = 160


def snippet(text: str, query: str, width: int = SNIPPET_CHARS) -> str:
    """The part of `text` around the first case-blind match of `query`, on
    one line, with "…" where it was cut; its start when there's no match."""
    line = " ".join(text.split())
    at = line.lower().find(query.lower())
    if len(line) <= width:
        return line
    start = 0 if at < 0 else max(0, min(at - width // 3, len(line) - width))
    end = start + width
    return ("…" if start > 0 else "") + line[start:end].strip() + ("…" if end < len(line) else "")


# A chat's title: its first message, cut.
MAX_TITLE_CHARS = 80
MAX_QUEUED = 1  # messages waiting behind the agent's turn in one chat (ADR 40)


def chat_title(message: str) -> str:
    line = " ".join(message.split())
    return line if len(line) <= MAX_TITLE_CHARS else line[: MAX_TITLE_CHARS - 1] + "…"


def folder_context(folder: Folder, subject: str | None, subject_name: str | None) -> str | None:
    """What a chat's folder tells the agent it is about; None for General."""
    if folder in (Folder.STRATEGY, Folder.REVIEW) and subject:
        name = repr(subject_name) if subject_name else "(since deleted)"
        return f"This chat is about the OpenTicker strategy {name} ({subject})."
    if folder is Folder.SCRIPT and subject:
        name = repr(subject_name) if subject_name else "(since deleted)"
        return f"This chat is about the OpenTicker hosted script {name} ({subject})."
    if folder is Folder.DEBRIEF and subject:
        return f"This chat is about the OpenTicker trading day {subject}."
    return None


READ_ONLY_LINE = (
    "This chat is read-only: you can read the desk but not change it. Tools that would "
    "change something are refused; say what you would do instead, so the user can do it."
)


def chat_prompt_context(context: str | None, job_id: str, access: Access = Access.TRADE) -> str:
    """What every chat turn adds to the agent's system prompt. The job's id
    is in it, so its process can be recognised after a restart."""
    lines = [
        (
            "The user is chatting with you from OpenTicker's web app, where your reply is "
            "shown as Markdown. Use OpenTicker's tools for anything about their desk."
        ),
    ]
    if context:
        lines.append(context)
    if access is Access.READ:
        lines.append(READ_ONLY_LINE)
    lines.append(f"(OpenTicker agent job {job_id})")
    return "\n".join(lines)
