"""Hosted Python scripts (ADR 25 in docs/adr): their schedules, their limits,
and why a run ended. Pure."""

import signal
from dataclasses import dataclass, field
from datetime import datetime, time
from enum import StrEnum

from openticker.ports.models import Exchange

MAX_SCRIPT_BYTES = 262_144  # a strategy script is a few hundred lines
TRADING_WEEKDAYS = frozenset(range(5))  # Monday 0 to Friday 4
ALL_WEEKDAYS = frozenset(range(7))  # Saturday and Sunday trade only in special sessions
LOG_LIMIT_BYTES = 50 * 1024 * 1024  # one run's output; past it the run is stopped


class InvalidScriptError(Exception):
    pass


@dataclass(frozen=True)
class ScriptSchedule:
    """When the daemon runs a script by itself: from `start_time` on each of
    `weekdays` that `exchange` trades, until `stop_time` or the script exits."""

    start_time: time  # exchange-local
    stop_time: time | None = None  # None: runs until it exits by itself
    weekdays: frozenset[int] = field(default_factory=lambda: TRADING_WEEKDAYS)
    exchange: Exchange = Exchange.NSE  # whose holidays are skipped

    def __post_init__(self) -> None:
        if not self.weekdays or not self.weekdays <= ALL_WEEKDAYS:
            raise InvalidScriptError(
                f"weekdays must be some of 0 (Monday) to 6 (Sunday), got {sorted(self.weekdays)}"
            )
        if self.stop_time is not None and self.stop_time <= self.start_time:
            raise InvalidScriptError(
                f"stop_time {self.stop_time:%H:%M} must be after start_time {self.start_time:%H:%M}"
            )


@dataclass(frozen=True)
class ScriptLimits:
    memory_mb: int = 1024  # resident memory of the script and its children
    cpu_seconds: int = 3600  # CPU time of one run

    def __post_init__(self) -> None:
        if self.memory_mb < 64:
            raise InvalidScriptError(
                f"the memory limit must be at least 64 MB, got {self.memory_mb}"
            )
        if self.cpu_seconds < 1:
            raise InvalidScriptError(
                f"the CPU limit must be at least 1 second, got {self.cpu_seconds}"
            )


class ScriptCommandKind(StrEnum):
    START = "start"
    STOP = "stop"


class ScriptCommandStatus(StrEnum):
    PENDING = "pending"  # waiting for the daemon's supervisor
    DONE = "done"
    REFUSED = "refused"  # `outcome` says why


@dataclass(frozen=True)
class ScriptCommand:
    id: int
    script_id: str
    kind: ScriptCommandKind
    triggered_by: str
    status: ScriptCommandStatus
    created_at: datetime  # tz-aware UTC
    outcome: str | None = None
    processed_at: datetime | None = None


class ScriptRunStatus(StrEnum):
    RUNNING = "running"
    STOPPING = "stopping"  # asked to stop; killed if it hasn't within STOP_GRACE
    ENDED = "ended"


class ScriptStopReason(StrEnum):
    EXITED = "exited"  # finished by itself with exit code 0
    FAILED = "failed"  # exited with an error, or was killed by a signal we didn't send
    STOPPED = "stopped"  # stop_script
    SCHEDULE = "schedule"  # its stop_time
    MEMORY_LIMIT = "memory_limit"
    CPU_LIMIT = "cpu_limit"
    LOG_LIMIT = "log_limit"  # printed more than LOG_LIMIT_BYTES
    DAEMON_STOPPED = "daemon_stopped"  # openticker-serve shut down
    LOST = "lost"  # gone when openticker-serve came back; how it ended is unknown
    START_FAILED = "start_failed"


@dataclass(frozen=True)
class ScriptRun:
    id: str
    script_id: str
    status: ScriptRunStatus
    trigger: str  # who started it: mcp, rest:<key>, schedule, recovery
    started_at: datetime  # tz-aware UTC
    pid: int | None = None
    stop_reason: ScriptStopReason | None = None
    stop_detail: str | None = None
    stop_requested_at: datetime | None = None  # tz-aware UTC
    exit_code: int | None = None
    ended_at: datetime | None = None  # tz-aware UTC


# Runs that ended because openticker-serve wasn't there to keep them. They
# don't count as the day's scheduled run, so the schedule starts it again.
ENDED_BY_ABSENCE = frozenset({ScriptStopReason.DAEMON_STOPPED, ScriptStopReason.LOST})


def exit_reason(returncode: int | None) -> tuple[ScriptStopReason, str]:
    """Why a script that nobody asked to stop ended, from its exit status.
    None: it outlived a daemon restart, so its status can't be read."""
    if returncode is None:
        return ScriptStopReason.EXITED, "exited; its exit code is unknown (it outlived a restart)"
    if returncode == 0:
        return ScriptStopReason.EXITED, "exited with code 0"
    if returncode == -signal.SIGXCPU:
        return ScriptStopReason.CPU_LIMIT, "used up its CPU time (SIGXCPU)"
    if returncode < 0:
        return ScriptStopReason.FAILED, f"killed by {_signal_name(-returncode)}"
    return ScriptStopReason.FAILED, f"exited with code {returncode}"


def _signal_name(number: int) -> str:
    try:
        return signal.Signals(number).name
    except ValueError:
        return f"signal {number}"
