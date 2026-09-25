"""The processes agent jobs run in (ADR 29 in docs/adr): the user's own
coding agent, started headless by the daemon, each the leader of its own
process group."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from openticker.core.agents.jobs import Harness
from openticker.ports.script_process_port import Exited


@dataclass(frozen=True)
class AgentLaunch:
    job_id: str
    harness: Harness
    prompt: str
    labs_dir: Path  # the agent's working directory: its skills, agents and notes
    log_path: Path  # what the agent prints while it works
    result_path: Path  # its final answer
    api_key: str = field(repr=False)  # the job's own key, scoped to its kind
    mcp_url: str  # openticker-serve's MCP endpoint
    max_budget_usd: float | None = None


@dataclass(frozen=True)
class AgentOutcome:
    summary: str | None  # the agent's final answer
    cost_usd: float | None  # when the harness reports it


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

    def outcome(self, harness: Harness, result_path: Path) -> AgentOutcome: ...
