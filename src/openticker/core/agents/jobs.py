"""Agent jobs (ADR 29 in docs/adr): the user's own coding agent, run headless
by the daemon in `labs/`, with a key that reaches only what the job's kind
may. A review reads one strategy and writes its verdict into that
strategy's note. A debrief is a desk job, about no one strategy: it reads a
trading day and writes the brain's notes on it. Pure."""

import re
import signal
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import TYPE_CHECKING

from openticker.core.brain.notes import day_title

if TYPE_CHECKING:
    from openticker.core.agents.choices import FolderKind, RunChoice

# The part of a job's answer kept with the job: a verdict, not a transcript.
MAX_SUMMARY_CHARS = 2_000


class AgentJobError(Exception):
    pass


class Harness(StrEnum):
    CLAUDE = "claude"  # Claude Code, `claude -p`
    CODEX = "codex"  # Codex, `codex exec`


class AgentJobKind(StrEnum):
    REVIEW = "review"  # one strategy
    DEBRIEF = "debrief"  # one trading day, the whole desk
    CHAT = "chat"  # one message in a chat (ADR 40)


class AgentJobStatus(StrEnum):
    PENDING = "pending"  # waiting for the daemon
    RUNNING = "running"
    STOPPING = "stopping"  # asked to stop; killed if it hasn't within the grace
    ENDED = "ended"


class Verdict(StrEnum):
    """A review's one verdict (ADR 29 in docs/adr), or not yet: under 10 runs after costs."""

    KEEP = "keep"
    CHANGE = "change"  # change one thing, as a new strategy
    RETIRE = "retire"
    NOT_YET = "not_yet"


class AgentJobEndReason(StrEnum):
    FINISHED = "finished"  # the agent exited with code 0
    FAILED = "failed"  # exited with an error, or was killed by a signal we didn't send
    TIMEOUT = "timeout"
    STOPPED = "stopped"  # stop_agent_job
    REFUSED = "refused"  # never started: the day's cap, or the strategy is gone
    START_FAILED = "start_failed"  # the harness couldn't be started
    DAEMON_STOPPED = "daemon_stopped"
    LOST = "lost"  # running when openticker-serve went away


@dataclass(frozen=True)
class AgentSettings:
    harness: Harness = Harness.CLAUDE
    timeout: timedelta = timedelta(minutes=15)
    jobs_per_day: int = 20
    max_budget_usd: float | None = None  # Claude Code only; Codex has no spend cap
    chat_turns_at_once: int = 2  # the chat lane's, beside the one background job (ADR 40)
    model: str | None = None  # None: the harness's own default
    effort: str | None = None  # an Effort the harness offers; None: its default
    # Each folder kind's resolved choice, once Settings are read (ADR 40).
    choices: "Mapping[FolderKind, RunChoice]" = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.timeout < timedelta(minutes=1):
            raise AgentJobError(f"the job timeout must be at least a minute, got {self.timeout}")
        if self.jobs_per_day < 1:
            raise AgentJobError(f"jobs per day must be at least 1, got {self.jobs_per_day}")
        if self.max_budget_usd is not None and self.max_budget_usd <= 0:
            raise AgentJobError(f"the budget must be above 0, got {self.max_budget_usd}")


@dataclass(frozen=True)
class AgentJob:
    id: str
    kind: AgentJobKind
    strategy_id: str | None  # a review's; None for a debrief
    harness: Harness
    status: AgentJobStatus
    trigger: str  # who asked: mcp, rest:<key>, schedule
    created_at: datetime  # tz-aware UTC
    started_at: datetime | None = None
    pid: int | None = None
    stop_requested_at: datetime | None = None
    end_reason: AgentJobEndReason | None = None
    end_detail: str | None = None
    exit_code: int | None = None
    ended_at: datetime | None = None
    summary: str | None = None  # the agent's final answer, capped
    cost_usd: float | None = None  # when the harness reports it
    subject: date | None = None  # the trading date a debrief covers
    # A chat's turn, and what each run used (ADR 40). None: not recorded.
    thread_id: str | None = None
    prompt: str | None = None  # a chat turn's message
    model: str | None = None  # as asked
    effort: str | None = None  # as asked
    model_used: str | None = None  # as the harness reported
    session_id: str | None = None  # the harness's conversation, to resume
    input_tokens: int | None = None
    output_tokens: int | None = None
    duration_ms: int | None = None


def harness_name(harness: Harness) -> str:
    return "Claude Code" if harness is Harness.CLAUDE else "Codex"


def start_failure(harness: Harness, error: Exception) -> str:
    """Why a job's process didn't start, said for the user."""
    if isinstance(error, FileNotFoundError):
        return (
            f"{harness_name(harness)} is not installed on this machine (not on the PATH jobs get)"
        )
    return f"could not start: {error}"


def job_title(kind: AgentJobKind, strategy_name: str | None, subject: date | None) -> str:
    """What people see a job called: "Review of NIFTY short straddle",
    "Debrief of Mon 5 Oct"."""
    if kind is AgentJobKind.DEBRIEF:
        return f"Debrief of {day_title(subject)}" if subject else "Debrief"
    if kind is AgentJobKind.CHAT:
        return "Chat"
    return f"Review of {strategy_name or 'a deleted strategy'}"


def exit_reason(returncode: int | None) -> tuple[AgentJobEndReason, str]:
    if returncode == 0:
        return AgentJobEndReason.FINISHED, "exited with code 0"
    if returncode is None:
        return AgentJobEndReason.FAILED, "its exit code is unknown"
    if returncode < 0:
        try:
            name = signal.Signals(-returncode).name
        except ValueError:
            name = f"signal {-returncode}"
        return AgentJobEndReason.FAILED, f"killed by {name}"
    return AgentJobEndReason.FAILED, f"exited with code {returncode}"


SCHEDULE_TRIGGER = "schedule: "  # how a job due on its own is asked for: the debrief


def review_prompt(strategy_name: str, strategy_id: str, job_id: str) -> str:
    """What a review job is asked. The job's id is in it, so its process can
    be recognised after a restart."""
    return (
        f"Review the OpenTicker strategy {strategy_name!r} ({strategy_id}) with the "
        f"review-strategy skill, and write the entry in notes/{strategy_name}.md. "
        "This is an unattended job: nobody will answer questions, so decide from the "
        "evidence and the skill. Finish with the skill's short summary, starting with "
        f"the verdict. (OpenTicker agent job {job_id})"
    )


def debrief_prompt(trading_date: date, job_id: str, trigger: str) -> str:
    """What a debrief job is asked. The job's id is in it, so its process can
    be recognised after a restart."""
    due = "It is due after the close. " if trigger.startswith(SCHEDULE_TRIGGER) else ""
    return (
        f"Debrief the OpenTicker trading day {trading_date.isoformat()} "
        f"({trading_date:%A %d %B %Y}) with the debrief-day skill. {due}"
        "This is an unattended job: nobody will answer questions, so decide from the "
        "record and the skill. Write only through OpenTicker's brain tools. Finish with "
        f"the skill's short summary, starting with the day's headline. (OpenTicker agent "
        f"job {job_id})"
    )


def capped(text: str | None) -> str | None:
    if text is None:
        return None
    text = text.strip()
    if len(text) <= MAX_SUMMARY_CHARS:
        return text
    return text[: MAX_SUMMARY_CHARS - 1] + "…"


# A review's summary starts with its verdict, maybe under a dated heading or in bold.
_VERDICT = re.compile(
    r"^[\s#*_>-]*(?:\d{4}-\d{2}-\d{2}\s*:?\s*)?(?:verdict\s*:\s*)?[*_]*"
    r"(keep|change|retire|not yet)\b",
    re.IGNORECASE,
)


def verdict_of(summary: str | None) -> Verdict | None:
    """The verdict a review's summary leads with; None when it leads with none."""
    found = _VERDICT.match(summary or "")
    if found is None:
        return None
    return Verdict(found.group(1).lower().replace(" ", "_"))
