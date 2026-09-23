"""Hosted Python scripts as the MCP server and the REST API manage them (ADR
25 in docs/adr): upload, change, schedule, start, stop, read logs. Nothing
here starts a process. A start or stop is written as a command the daemon's
supervisor carries out within about a second, so these work the same
whether or not it is running."""

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from openticker.core.scripts.models import (
    MAX_SCRIPT_BYTES,
    InvalidScriptError,
    ScriptCommand,
    ScriptCommandKind,
    ScriptCommandStatus,
    ScriptRun,
    ScriptSchedule,
)
from openticker.storage import script_files
from openticker.storage.sqlite import scripts_repo
from openticker.storage.sqlite.scripts_repo import StoredScript
from openticker.storage.sqlite.strategies_repo import write_transaction

MAX_LOG_LINES = 1000
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _.-]{0,59}")


class UnknownScriptError(LookupError):
    pass


class ScriptRunningError(Exception):
    """Refused while the script runs, or is about to."""


class ScriptStateError(Exception):
    """The request doesn't fit what the script is doing now."""


@dataclass(frozen=True)
class ScriptSummary:
    script: StoredScript
    active: ScriptRun | None  # running or stopping
    last: ScriptRun | None  # the latest run, active or not


@dataclass(frozen=True)
class ScriptDetail:
    script: StoredScript
    runs: list[ScriptRun]  # newest first
    commands: list[ScriptCommand]  # newest first
    source: str | None  # only when asked for


@dataclass(frozen=True)
class ScriptLog:
    script: StoredScript
    run: ScriptRun
    lines: list[str]
    truncated: bool  # earlier lines were left out


def upload_script(name: str, source: str, now: datetime) -> StoredScript:
    digest, size = _check(name, source)
    with write_transaction() as session:
        stored = scripts_repo.insert_script(session, name, digest, size, now)
        script_files.write_source(stored.id, source)
    return stored


def update_script(script_id: str, name: str, source: str, now: datetime) -> StoredScript:
    """Replaces the name and the whole source. Refused while it runs."""
    digest, size = _check(name, source)
    with write_transaction() as session:
        _refuse_while_running(session, _script(session, script_id), "changing")
        stored = scripts_repo.update_script(session, script_id, name, digest, size, now)
        assert stored is not None  # _script found it under the same lock
        script_files.write_source(script_id, source)
    return stored


def delete_script(script_id: str) -> None:
    """The script, its runs and its logs. Refused while it runs."""
    with write_transaction() as session:
        _refuse_while_running(session, _script(session, script_id), "deleting")
        scripts_repo.delete_script(session, script_id)
    script_files.delete_files(script_id)


def get_script(script_id: str, runs: int, include_source: bool) -> ScriptDetail:
    stored = _find(script_id)
    return ScriptDetail(
        script=stored,
        runs=scripts_repo.recent_runs(script_id, runs),
        commands=scripts_repo.recent_commands(script_id, runs),
        source=script_files.read_source(script_id) if include_source else None,
    )


def list_scripts() -> list[ScriptSummary]:
    summaries = []
    for stored in scripts_repo.list_scripts():
        last = next(iter(scripts_repo.recent_runs(stored.id, 1)), None)
        active = last if last is not None and last.ended_at is None else None
        summaries.append(ScriptSummary(stored, active, last))
    return summaries


def schedule_script(script_id: str, schedule: ScriptSchedule) -> StoredScript:
    """Runs it from start_time on its weekdays, skipping days its exchange
    doesn't trade, until stop_time. Replaces any schedule it had."""
    with write_transaction() as session:
        _script(session, script_id)
        scripts_repo.set_schedule(session, script_id, schedule)
    return _find(script_id)


def unschedule_script(script_id: str) -> StoredScript:
    """No more scheduled starts or stops; a run already going carries on."""
    with write_transaction() as session:
        _script(session, script_id)
        scripts_repo.set_schedule(session, script_id, None)
    return _find(script_id)


def request_start(script_id: str, triggered_by: str, now: datetime) -> ScriptCommand:
    with write_transaction() as session:
        stored = _script(session, script_id)
        active = scripts_repo.active_run(session, script_id)
        if active is not None:
            raise ScriptStateError(f"{stored.name!r} is already running (run {active.id})")
        if _pending(session, script_id, ScriptCommandKind.START):
            raise ScriptStateError(f"{stored.name!r} is already being started")
        return scripts_repo.add_command(
            session, script_id, ScriptCommandKind.START, triggered_by, now
        )


def request_stop(script_id: str, triggered_by: str, now: datetime) -> ScriptCommand:
    """Asks the script to stop, and kills it if it hasn't within a few
    seconds. A start not carried out yet is cancelled instead. A scheduled
    script stopped this way isn't started again until its next day."""
    with write_transaction() as session:
        stored = _script(session, script_id)
        cancelled = False
        for command in _pending(session, script_id, ScriptCommandKind.START):
            scripts_repo.settle_command(
                session, command.id, ScriptCommandStatus.REFUSED, "cancelled by a stop", now
            )
            cancelled = True
        if scripts_repo.active_run(session, script_id) is None and not cancelled:
            raise ScriptStateError(f"{stored.name!r} is not running; nothing to stop")
        return scripts_repo.add_command(
            session, script_id, ScriptCommandKind.STOP, triggered_by, now
        )


def get_logs(script_id: str, run_id: str | None, lines: int) -> ScriptLog:
    """A run's last `lines` lines of output: the latest run's by default."""
    stored = _find(script_id)
    if run_id is None:
        run = next(iter(scripts_repo.recent_runs(script_id, 1)), None)
        if run is None:
            raise ScriptStateError(f"{stored.name!r} has never run; start_script runs it")
    else:
        run = scripts_repo.find_run(run_id)
        if run is None or run.script_id != script_id:
            raise UnknownScriptError(f"{stored.name!r} has no run {run_id!r}")
    found, truncated = script_files.tail_log(script_id, run.id, min(lines, MAX_LOG_LINES))
    return ScriptLog(stored, run, found, truncated)


def _check(name: str, source: str) -> tuple[str, int]:
    """The source's SHA-256 and size, once it is known to be Python."""
    if not _NAME.fullmatch(name):
        raise InvalidScriptError(
            f"script name {name!r} must be 1-60 letters, digits, spaces, '.', '-' or '_', "
            "starting with a letter or digit"
        )
    encoded = source.encode("utf-8")
    if len(encoded) > MAX_SCRIPT_BYTES:
        raise InvalidScriptError(
            f"the script is {len(encoded):,} bytes; the most is {MAX_SCRIPT_BYTES:,}"
        )
    try:
        compile(source, "main.py", "exec", dont_inherit=True)  # parses, runs nothing
    except SyntaxError as exc:
        raise InvalidScriptError(f"not valid Python: {exc.msg} (line {exc.lineno})") from exc
    except ValueError as exc:  # null bytes
        raise InvalidScriptError(f"not valid Python: {exc}") from exc
    return hashlib.sha256(encoded).hexdigest(), len(encoded)


def _script(session: Session, script_id: str) -> StoredScript:
    stored = scripts_repo.load_script(session, script_id)
    if stored is None:
        raise UnknownScriptError(f"no script {script_id!r}; list_scripts shows them")
    return stored


def _find(script_id: str) -> StoredScript:
    stored = scripts_repo.find_script(script_id)
    if stored is None:
        raise UnknownScriptError(f"no script {script_id!r}; list_scripts shows them")
    return stored


def _pending(session: Session, script_id: str, kind: ScriptCommandKind) -> list[ScriptCommand]:
    return [c for c in scripts_repo.pending_commands_of(session, script_id) if c.kind is kind]


def _refuse_while_running(session: Session, stored: StoredScript, doing: str) -> None:
    if scripts_repo.active_run(session, stored.id) is not None or _pending(
        session, stored.id, ScriptCommandKind.START
    ):
        raise ScriptRunningError(f"{stored.name!r} is running; stop_script it before {doing} it")
