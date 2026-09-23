"""The daemon's side of hosted scripts (ADR 25 in docs/adr): carries out
start and stop commands, starts and stops scheduled scripts, holds each
run to its memory, CPU and log limits, and records how every run ended.
After a restart it takes back the scripts a previous daemon left running.

Each run gets its own API key, scoped to trading routes, created as it
starts and revoked as it ends. The key reaches the script only through its
environment and is stored only as a hash.
"""

import logging
import time as clock_time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from openticker.core.calendar.models import MarketCalendar
from openticker.core.scripts.models import (
    ENDED_BY_ABSENCE,
    LOG_LIMIT_BYTES,
    ScriptCommand,
    ScriptCommandKind,
    ScriptCommandStatus,
    ScriptLimits,
    ScriptRun,
    ScriptRunStatus,
    ScriptStopReason,
    exit_reason,
)
from openticker.core.scripts.schedule import in_window, stop_due
from openticker.events.bus import EventPublisher
from openticker.events.types import ScriptExited, ScriptStarted
from openticker.ports.models import EXCHANGE_TIMEZONE
from openticker.ports.script_process_port import (
    ScriptHostingUnsupportedError,
    ScriptLaunch,
    ScriptProcesses,
)
from openticker.storage import script_files
from openticker.storage.sqlite import scripts_repo
from openticker.storage.sqlite.api_keys_repo import DuplicateApiKeyNameError, revoke_api_key
from openticker.storage.sqlite.strategies_repo import write_transaction
from openticker.use_cases.api_keys import create_script_key, revoke_script_keys, script_key_name

log = logging.getLogger(__name__)

STOP_GRACE = timedelta(seconds=5)  # from SIGTERM to SIGKILL
KEPT_LOGS = 10  # runs per script whose output is kept
COMMANDS_PER_PASS = 50
SCHEDULE_TRIGGER = "schedule"
RECOVERY_TRIGGER = "recovery"


@dataclass(frozen=True)
class SupervisorContext:
    processes: ScriptProcesses
    events: EventPublisher
    calendar: MarketCalendar
    limits: ScriptLimits
    base_url: str  # where scripts reach openticker-serve's REST API


def recover_scripts(context: SupervisorContext, now: datetime) -> int:
    """How many runs a previous daemon left running are watched again. One
    whose process is gone ends `lost`; if it was started by hand it is
    started again, and a scheduled one is left to its schedule. Every other
    script key is revoked."""
    kept: set[str] = set()
    restart: list[str] = []
    for run in scripts_repo.active_runs():
        path = script_files.script_path(run.script_id)
        if run.pid is not None and context.processes.adopt(run.pid, path):
            kept.add(run.id)
            continue
        for stray in context.processes.find(path):  # started, but never recorded
            context.processes.stop(stray, force=True)
        if run.status is ScriptRunStatus.STOPPING and run.stop_reason is not None:
            _end(context, run, run.stop_reason, run.stop_detail or "", None, now)
            continue
        detail = "was not running when openticker-serve came back"
        if _end(context, run, ScriptStopReason.LOST, detail, None, now) and (
            run.trigger != SCHEDULE_TRIGGER
        ):
            restart.append(run.script_id)
    revoke_script_keys(kept, now)
    for script_id in restart:
        _launch(context, script_id, RECOVERY_TRIGGER, None, now)
    return len(kept)


def process_script_commands(context: SupervisorContext, now: datetime) -> None:
    for _ in range(COMMANDS_PER_PASS):
        command = scripts_repo.next_pending_command()
        if command is None:
            return
        if command.kind is ScriptCommandKind.START:
            _launch(context, command.script_id, command.triggered_by, command, now)
        else:
            _stop(context, command, now)


def start_scheduled_scripts(context: SupervisorContext, now: datetime) -> None:
    """Starts each scheduled script inside its window once a trading day.
    A run it ended by itself, or was stopped from, since today's start_time
    is that day's run; one openticker-serve's absence ended isn't."""
    today = now.astimezone(EXCHANGE_TIMEZONE).date()
    for stored in scripts_repo.list_scripts():
        schedule = stored.schedule
        if schedule is None:
            continue
        if not in_window(schedule, context.calendar, now):
            continue
        since = datetime.combine(today, schedule.start_time, EXCHANGE_TIMEZONE)
        runs = scripts_repo.runs_started_since(stored.id, since)
        if any(run.stop_reason not in ENDED_BY_ABSENCE for run in runs):
            continue
        _launch(context, stored.id, SCHEDULE_TRIGGER, None, now)  # not if still running


def watch_scripts(context: SupervisorContext, now: datetime) -> None:
    """Records every run that ended, kills one that outstayed a stop, and
    stops one past a limit or its stop_time."""
    runs = scripts_repo.active_runs()
    leaders = [run.pid for run in runs if run.pid is not None]
    memory: dict[int, int] | None = None
    for run in runs:
        if run.pid is None:
            continue  # recovery ends it
        exited = context.processes.poll(run.pid)
        if exited is not None:
            _finish(context, run, exited.returncode, now)
            continue
        if run.status is ScriptRunStatus.STOPPING:
            requested = run.stop_requested_at or now
            if now - requested >= STOP_GRACE:
                context.processes.stop(run.pid, force=True)
            continue
        if memory is None:
            memory = dict(context.processes.memory_kb(leaders))
        why = _over_limit(context.limits, run, memory.get(run.pid, 0), now)
        if why is not None:
            reason, detail = why
            _ask_to_stop(context, run, reason, detail, now)


def stop_all_scripts(
    context: SupervisorContext,
    clock: Callable[[], datetime],
    sleep: Callable[[float], None] = clock_time.sleep,
) -> None:
    """At shutdown: asks every script to stop, waits STOP_GRACE, kills the
    rest, and records each run as ended `daemon_stopped`."""
    runs = [run for run in scripts_repo.active_runs() if run.pid is not None]
    for run in runs:
        _ask_to_stop(
            context, run, ScriptStopReason.DAEMON_STOPPED, "openticker-serve shut down", clock()
        )
    deadline = clock() + STOP_GRACE
    killed = False
    waiting = {run.id: run for run in runs}
    codes: dict[str, int | None] = {}
    while waiting:
        for run in list(waiting.values()):
            assert run.pid is not None
            exited = context.processes.poll(run.pid)
            if exited is not None:
                codes[run.id] = exited.returncode
                del waiting[run.id]
        if waiting and clock() >= deadline:
            if killed:
                break  # not even SIGKILL: recorded as asked, the process may linger
            for run in waiting.values():
                assert run.pid is not None
                context.processes.stop(run.pid, force=True)
            killed = True
            deadline = clock() + STOP_GRACE
        if waiting:
            sleep(0.1)
    now = clock()
    for run in runs:
        _finish(context, run, codes.get(run.id), now)


def _launch(
    context: SupervisorContext,
    script_id: str,
    trigger: str,
    command: ScriptCommand | None,
    now: datetime,
) -> None:
    with write_transaction() as session:
        stored = scripts_repo.load_script(session, script_id)
        active = scripts_repo.active_run(session, script_id)
        if stored is None or active is not None:
            if command is not None:
                refusal = "the script was deleted"
                if active is not None:
                    refusal = f"already running (run {active.id})"
                scripts_repo.settle_command(
                    session, command.id, ScriptCommandStatus.REFUSED, refusal, now
                )
            return
        run = scripts_repo.add_run(session, script_id, trigger, now)
    local = now.astimezone(EXCHANGE_TIMEZONE)
    script_files.append_log(
        script_id, run.id, f"=== run {run.id} started {local:%Y-%m-%d %H:%M:%S %Z} by {trigger} ==="
    )
    try:
        key = create_script_key(script_id, run.id, now)
        pid = context.processes.start(
            ScriptLaunch(
                script_id=script_id,
                path=script_files.script_path(script_id),
                log_path=script_files.log_path(script_id, run.id),
                api_key=key,
                base_url=context.base_url,
                cpu_seconds=context.limits.cpu_seconds,
            )
        )
    except (ScriptHostingUnsupportedError, DuplicateApiKeyNameError, OSError) as exc:
        detail = f"could not start: {exc}"
        _end(context, run, ScriptStopReason.START_FAILED, detail, None, now)
        if command is not None:
            _settle(command, ScriptCommandStatus.REFUSED, detail, now)
        return
    with write_transaction() as session:
        scripts_repo.set_pid(session, run.id, pid)
        if command is not None:
            scripts_repo.settle_command(
                session, command.id, ScriptCommandStatus.DONE, f"started run {run.id}", now
            )
    kept = {kept_run.id for kept_run in scripts_repo.recent_runs(script_id, KEPT_LOGS)}
    script_files.prune_logs(script_id, kept)
    log.info("script %s started as run %s (pid %d)", stored.name, run.id, pid)
    context.events.publish(ScriptStarted(script_id, run.id, stored.name, trigger))


def _stop(context: SupervisorContext, command: ScriptCommand, now: datetime) -> None:
    with write_transaction() as session:
        run = scripts_repo.active_run(session, command.script_id)
        if run is None:
            scripts_repo.settle_command(
                session, command.id, ScriptCommandStatus.DONE, "was not running", now
            )
            return
        scripts_repo.request_stop(
            session, run.id, ScriptStopReason.STOPPED, f"stopped by {command.triggered_by}", now
        )
        scripts_repo.settle_command(
            session, command.id, ScriptCommandStatus.DONE, f"stopping run {run.id}", now
        )
    if run.pid is not None:
        context.processes.stop(run.pid, force=False)


def _over_limit(
    limits: ScriptLimits, run: ScriptRun, memory_kb: int, now: datetime
) -> tuple[ScriptStopReason, str] | None:
    if memory_kb > limits.memory_mb * 1024:
        return (
            ScriptStopReason.MEMORY_LIMIT,
            f"used {memory_kb // 1024} MB, over its {limits.memory_mb} MB limit",
        )
    size = script_files.log_size(run.script_id, run.id)
    if size > LOG_LIMIT_BYTES:
        megabytes = LOG_LIMIT_BYTES // (1024 * 1024)
        return (
            ScriptStopReason.LOG_LIMIT,
            f"printed {size // (1024 * 1024)} MB, over the {megabytes} MB a run may",
        )
    stored = scripts_repo.find_script(run.script_id)
    if stored is not None and stored.schedule is not None:
        at = stop_due(stored.schedule, run.started_at, now)
        if at is not None:
            return (
                ScriptStopReason.SCHEDULE,
                f"its stop_time {at.astimezone(EXCHANGE_TIMEZONE):%H:%M}",
            )
    return None


def _ask_to_stop(
    context: SupervisorContext,
    run: ScriptRun,
    reason: ScriptStopReason,
    detail: str,
    now: datetime,
) -> None:
    """SIGTERM, or SIGKILL straight away for memory: a script past its limit
    can take the machine's memory before it notices a polite signal."""
    with write_transaction() as session:
        scripts_repo.request_stop(session, run.id, reason, detail, now)
    if run.pid is not None:
        log.info("stopping script run %s: %s", run.id, detail)
        context.processes.stop(run.pid, force=reason is ScriptStopReason.MEMORY_LIMIT)


def _finish(
    context: SupervisorContext, run: ScriptRun, returncode: int | None, now: datetime
) -> None:
    """A run whose process has ended: the reason it was asked to stop wins
    over the exit status, which the detail still gives."""
    current = scripts_repo.find_run(run.id) or run
    reason, detail = exit_reason(returncode)
    if current.stop_reason is not None:
        reason, detail = current.stop_reason, f"{current.stop_detail}; {detail}"
    _end(context, current, reason, detail, returncode, now)


def _end(
    context: SupervisorContext,
    run: ScriptRun,
    reason: ScriptStopReason,
    detail: str,
    exit_code: int | None,
    now: datetime,
) -> bool:
    """False when it had already ended."""
    with write_transaction() as session:
        ended = scripts_repo.end_run(session, run.id, reason, detail, exit_code, now)
        stored = scripts_repo.load_script(session, run.script_id)
    revoke_api_key(script_key_name(run.id), now)
    if ended is None:
        return False
    script_files.append_log(
        run.script_id, run.id, f"=== run {run.id} ended: {reason}, {detail} ==="
    )
    log.info("script run %s ended: %s, %s", run.id, reason, detail)
    context.events.publish(
        ScriptExited(
            run.script_id, run.id, stored.name if stored else run.script_id, reason, detail
        )
    )
    return True


def _settle(
    command: ScriptCommand, status: ScriptCommandStatus, outcome: str, now: datetime
) -> None:
    with write_transaction() as session:
        scripts_repo.settle_command(session, command.id, status, outcome, now)
