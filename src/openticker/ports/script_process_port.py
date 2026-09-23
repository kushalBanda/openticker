"""The child processes hosted scripts run in (ADR 25 in docs/adr). Only the
daemon starts them; each is the leader of its own process group, so a
signal reaches anything the script started too."""

from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


class ScriptHostingUnsupportedError(Exception):
    """Scripts can't be run here with their limits, so they aren't run at all."""


@dataclass(frozen=True)
class ScriptLaunch:
    script_id: str
    path: Path  # the script file; also how its process is recognised later
    log_path: Path  # stdout and stderr are appended here
    api_key: str = field(repr=False)  # the run's own key, scoped to trading routes
    base_url: str  # where openticker-serve's REST API answers
    cpu_seconds: int


@dataclass(frozen=True)
class Exited:
    returncode: int | None  # None: not our child (it outlived a restart), so unknown


class ScriptProcesses(Protocol):
    def start(self, launch: ScriptLaunch) -> int:
        """The new process's id. Its environment is built from nothing but
        what the launch names."""
        ...

    def poll(self, pid: int) -> Exited | None:
        """None while it runs."""
        ...

    def adopt(self, pid: int, path: Path) -> bool:
        """Watch a process a previous daemon started, if `pid` is still that
        script; False when it is gone or is something else now."""
        ...

    def find(self, path: Path) -> list[int]:
        """Processes running this script file, whoever started them."""
        ...

    def stop(self, pid: int, force: bool) -> None:
        """SIGTERM to its process group, or SIGKILL when `force`."""
        ...

    def memory_kb(self, leaders: Collection[int]) -> Mapping[int, int]:
        """Memory in KB each of these process groups holds, keyed by its leader."""
        ...
