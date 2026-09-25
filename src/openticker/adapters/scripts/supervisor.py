"""Runs hosted scripts as child processes (ADR 25 in docs/adr, refining ADR
15). POSIX only: CPU time is limited with setrlimit in the child, and
memory by measuring each script's process group every second, because
macOS refuses to lower a process's memory limits. On macOS the measure is
the physical footprint Activity Monitor shows, since under memory pressure
most of a process's pages are compressed and its resident size says little;
on Linux it is the resident size.

The child's environment is built from nothing, never copied from ours:
the daemon holds broker keys, SMTP and Slack settings, and a script must
not be handed any of them by accident.
"""

import ctypes
import os
import signal
import subprocess
import sys
from collections.abc import Collection, Mapping
from pathlib import Path

from openticker.ports.script_process_port import (
    Exited,
    ScriptHostingUnsupportedError,
    ScriptLaunch,
)

# Runs in the child before the script: limits its CPU time, then replaces
# itself with the script, so the process is `python -u <script>`. One line,
# so `ps` shows it on one line too.
_LAUNCHER = (
    "import os, resource, sys; cpu = int(sys.argv[1]); "
    "resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 5)); "
    "os.execv(sys.executable, [sys.executable, '-u', sys.argv[2]])"
)


def script_env(
    script_id: str, api_key: str, base_url: str, home: Path, parent: Mapping[str, str]
) -> dict[str, str]:
    """Everything a script's process is given. Only `PATH` and `LANG` come
    from the daemon's own environment."""
    return {
        "PATH": parent.get("PATH") or os.defpath,
        "HOME": str(home),
        "LANG": parent.get("LANG") or "C.UTF-8",
        "PYTHONUNBUFFERED": "1",
        "OPENTICKER_URL": base_url,
        "OPENTICKER_API_KEY": api_key,
        "OPENTICKER_SCRIPT_ID": script_id,
    }


class ProcessSupervisor:
    def __init__(self, python: str = sys.executable) -> None:
        self._python = python
        self._children: dict[int, subprocess.Popen[bytes]] = {}
        self._adopted: set[int] = set()

    def start(self, launch: ScriptLaunch) -> int:
        if os.name != "posix":
            raise ScriptHostingUnsupportedError(
                "scripts run only on Linux and macOS, where their CPU and memory can be limited"
            )
        home = launch.path.parent
        with launch.log_path.open("ab") as log:
            process = subprocess.Popen(
                [self._python, "-c", _LAUNCHER, str(launch.cpu_seconds), str(launch.path)],
                cwd=home,
                env=script_env(launch.script_id, launch.api_key, launch.base_url, home, os.environ),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,  # its own process group, apart from the daemon's
            )
        self._children[process.pid] = process
        return process.pid

    def poll(self, pid: int) -> Exited | None:
        child = self._children.get(pid)
        if child is not None:
            returncode = child.poll()
            if returncode is None:
                return None
            del self._children[pid]
            return Exited(returncode)
        if alive(pid):
            return None
        self._adopted.discard(pid)
        return Exited(None)

    def adopt(self, pid: int, path: Path) -> bool:
        if pid in self._children or pid in self._adopted:
            return True
        if not alive(pid) or pid not in self.find(path):
            return False
        self._adopted.add(pid)
        return True

    def find(self, path: Path) -> list[int]:
        listing = ps("pid=", "command=")
        found = []
        for line in listing:
            pid, _, command = line.strip().partition(" ")
            if pid.isdigit() and command.endswith(" " + str(path)):  # python -u <path>
                found.append(int(pid))
        return found

    def stop(self, pid: int, force: bool) -> None:
        try:
            os.killpg(pid, signal.SIGKILL if force else signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass  # already gone

    def memory_kb(self, leaders: Collection[int]) -> Mapping[int, int]:
        wanted = set(leaders)
        totals: dict[int, int] = {}
        for line in ps("pid=", "pgid=", "rss="):
            fields = line.split()
            if len(fields) != 3 or not all(field.isdigit() for field in fields):
                continue
            pid, group, resident = (int(field) for field in fields)
            if group in wanted:
                totals[group] = totals.get(group, 0) + (_footprint_kb(pid) or resident)
        return totals


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, but isn't ours
    return True


class _RusageInfoV0(ctypes.Structure):
    """<libproc.h> rusage_info_v0, up to the field read here."""

    _fields_ = [
        ("uuid", ctypes.c_uint8 * 16),
        ("user_time", ctypes.c_uint64),
        ("system_time", ctypes.c_uint64),
        ("pkg_idle_wkups", ctypes.c_uint64),
        ("interrupt_wkups", ctypes.c_uint64),
        ("pageins", ctypes.c_uint64),
        ("wired_size", ctypes.c_uint64),
        ("resident_size", ctypes.c_uint64),
        ("phys_footprint", ctypes.c_uint64),
        ("proc_start_abstime", ctypes.c_uint64),
        ("proc_exit_abstime", ctypes.c_uint64),
    ]


_libproc: ctypes.CDLL | None = None


def _footprint_kb(pid: int) -> int | None:
    """macOS only: the process's physical footprint, compressed pages
    included. None elsewhere, or when it can't be read."""
    global _libproc
    if sys.platform != "darwin":
        return None
    if _libproc is None:
        _libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
    info = _RusageInfoV0()
    if _libproc.proc_pid_rusage(pid, 0, ctypes.byref(info)) != 0:  # 0: RUSAGE_INFO_V0
        return None
    return int(info.phys_footprint) // 1024


def ps(*columns: str) -> list[str]:
    arguments = ["ps", "-A", "-ww"]
    for column in columns:
        arguments += ["-o", column]
    completed = subprocess.run(arguments, capture_output=True, text=True, check=False)
    return completed.stdout.splitlines()
