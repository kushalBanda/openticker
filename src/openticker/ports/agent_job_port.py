"""The processes agent jobs run in (ADR 29 in docs/adr): the user's own
coding agent, started headless by the daemon, each the leader of its own
process group."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from openticker.core.agents.choices import ModelOption
from openticker.core.agents.jobs import Harness
from openticker.ports.script_process_port import Exited


@dataclass(frozen=True)
class AgentLaunch:
    job_id: str
    harness: Harness
    prompt: str
    labs_dir: Path  # the agent's working directory: its skills, agents and notes
    log_path: Path  # what the agent prints on stderr
    events_path: Path  # its event stream on stdout (ADR 40)
    result_path: Path  # Codex's final answer
    api_key: str = field(repr=False)  # the job's own key, scoped to its kind
    mcp_url: str  # openticker-serve's MCP endpoint
    max_budget_usd: float | None = None
    agent: str | None = "reviewer"  # the labs agent that runs it; None for a chat
    writes_notes: bool = True  # False: no file tools at all, a read-only sandbox
    model: str | None = None  # None: the harness's own default
    effort: str | None = None
    resume_session: str | None = None  # a chat's conversation so far
    context: str | None = None  # added to a chat's system prompt


@dataclass(frozen=True)
class AgentOutcome:
    summary: str | None  # the agent's final answer
    cost_usd: float | None  # when the harness reports it
    session_id: str | None = None
    model_used: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    duration_ms: int | None = None
    error: str | None = None  # why the harness says the turn failed


@dataclass(frozen=True)
class HarnessInfo:
    """Whether a harness's CLI is on this machine, its version, and the
    models it lists: () when it lists none, and any name is typed."""

    harness: Harness
    installed: bool
    version: str | None = None
    models: tuple[ModelOption, ...] = ()
    default_model: ModelOption | None = None  # what runs when none is named, if it says


class AgentProcesses(Protocol):
    def start(self, launch: AgentLaunch) -> int:
        """The new process's id. Its environment is built from nothing but
        what the harness needs to sign in, and the job's key."""
        ...

    def poll(self, pid: int) -> Exited | None:
        """None while it runs."""
        ...

    def is_job(self, pid: int, job_id: str) -> bool:
        """Whether `pid` is still that job's process (after a restart)."""
        ...

    def stop(self, pid: int, force: bool) -> None:
        """SIGTERM to its process group, or SIGKILL when `force`."""
        ...

    def outcome(self, harness: Harness, events_path: Path, result_path: Path) -> AgentOutcome: ...
