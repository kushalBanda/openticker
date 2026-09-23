"""A `ScriptProcesses` that starts nothing: tests say when a process exits,
how much memory it holds, and which processes a restarted daemon finds."""

from collections.abc import Collection, Mapping
from pathlib import Path

from openticker.ports.script_process_port import (
    Exited,
    ScriptHostingUnsupportedError,
    ScriptLaunch,
)


class FakeProcesses:
    def __init__(self) -> None:
        self.launches: list[ScriptLaunch] = []
        self.signals: list[tuple[int, bool]] = []  # (pid, force)
        self.running: dict[int, Path] = {}  # pid -> script path, as `ps` would show
        self.exits: dict[int, int | None] = {}  # pid -> return code, once it has exited
        self.memory: dict[int, int] = {}  # pid -> resident KB
        self.adopted: set[int] = set()
        self.unsupported = False
        self.exit_on_signal = True  # False: ignores SIGTERM, as a stuck script would
        self.unkillable = False  # True: not even SIGKILL ends it (stuck in the kernel)
        self._next_pid = 4000

    def start(self, launch: ScriptLaunch) -> int:
        if self.unsupported:
            raise ScriptHostingUnsupportedError("scripts run only on Linux and macOS")
        self.launches.append(launch)
        self._next_pid += 1
        self.running[self._next_pid] = launch.path
        return self._next_pid

    def exit(self, pid: int, returncode: int | None) -> None:
        self.running.pop(pid, None)
        self.exits[pid] = returncode

    def poll(self, pid: int) -> Exited | None:
        if pid in self.running:
            return None
        return Exited(self.exits.get(pid))

    def adopt(self, pid: int, path: Path) -> bool:
        if self.running.get(pid) != path:
            return False
        self.adopted.add(pid)
        return True

    def find(self, path: Path) -> list[int]:
        return [pid for pid, running in self.running.items() if running == path]

    def stop(self, pid: int, force: bool) -> None:
        self.signals.append((pid, force))
        if pid in self.running and not self.unkillable and (force or self.exit_on_signal):
            self.exit(pid, -9 if force else -15)

    def memory_kb(self, leaders: Collection[int]) -> Mapping[int, int]:
        return {pid: kb for pid, kb in self.memory.items() if pid in leaders}
