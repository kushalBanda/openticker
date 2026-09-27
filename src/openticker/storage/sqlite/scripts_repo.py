"""Hosted scripts, the commands sent to them, and their runs (ADR 25 in
docs/adr). The source files and logs live beside the database, in
storage/script_files.py."""

import json
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, time
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from openticker.core.scripts.models import (
    ScriptCommand,
    ScriptCommandKind,
    ScriptCommandStatus,
    ScriptRun,
    ScriptRunStatus,
    ScriptSchedule,
    ScriptStopReason,
)
from openticker.ports.models import Exchange
from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.models import ScriptCommandRow, ScriptRow, ScriptRunRow

SCHEDULE_VERSION = 1


class DuplicateScriptNameError(Exception):
    pass


@dataclass(frozen=True)
class StoredScript:
    id: str
    name: str
    source_sha256: str
    source_bytes: int
    schedule: ScriptSchedule | None  # None: runs only on start_script
    created_at: datetime  # tz-aware UTC
    updated_at: datetime  # tz-aware UTC


def insert_script(
    session: Session, name: str, source_sha256: str, source_bytes: int, now: datetime
) -> StoredScript:
    _refuse_taken(session, name)
    row = ScriptRow(
        id="scr_" + secrets.token_hex(6),
        name=name,
        source_sha256=source_sha256,
        source_bytes=source_bytes,
        schedule=None,
        created_at=_naive(now),
        updated_at=_naive(now),
    )
    session.add(row)
    session.flush()
    return _stored(row)


def update_script(
    session: Session,
    script_id: str,
    name: str,
    source_sha256: str,
    source_bytes: int,
    now: datetime,
) -> StoredScript | None:
    row = session.get(ScriptRow, script_id)
    if row is None:
        return None
    if name != row.name:
        _refuse_taken(session, name)
    row.name = name
    row.source_sha256 = source_sha256
    row.source_bytes = source_bytes
    row.updated_at = _naive(now)
    session.flush()
    return _stored(row)


def delete_script(session: Session, script_id: str) -> None:
    """The script, its runs and its commands."""
    for table in (ScriptCommandRow, ScriptRunRow):
        session.execute(delete(table).where(table.script_id == script_id))
    session.execute(delete(ScriptRow).where(ScriptRow.id == script_id))


def load_script(session: Session, script_id: str) -> StoredScript | None:
    row = session.get(ScriptRow, script_id)
    return _stored(row) if row else None


def find_script(script_id: str) -> StoredScript | None:
    with Session(get_engine()) as session:
        return load_script(session, script_id)


def list_scripts() -> list[StoredScript]:
    with Session(get_engine()) as session:
        rows = session.scalars(select(ScriptRow).order_by(ScriptRow.name)).all()
        return [_stored(row) for row in rows]


def set_schedule(session: Session, script_id: str, schedule: ScriptSchedule | None) -> None:
    row = session.get(ScriptRow, script_id)
    if row is not None:
        row.schedule = json.dumps(_encode_schedule(schedule)) if schedule else None


def add_command(
    session: Session, script_id: str, kind: ScriptCommandKind, triggered_by: str, now: datetime
) -> ScriptCommand:
    row = ScriptCommandRow(
        script_id=script_id,
        kind=kind.value,
        triggered_by=triggered_by,
        status=ScriptCommandStatus.PENDING.value,
        outcome=None,
        created_at=_naive(now),
        processed_at=None,
    )
    session.add(row)
    session.flush()
    return _command(row)


def pending_commands_of(session: Session, script_id: str) -> list[ScriptCommand]:
    statement = (
        select(ScriptCommandRow)
        .where(
            ScriptCommandRow.script_id == script_id,
            ScriptCommandRow.status == ScriptCommandStatus.PENDING.value,
        )
        .order_by(ScriptCommandRow.id)
    )
    return [_command(row) for row in session.scalars(statement).all()]


def next_pending_command() -> ScriptCommand | None:
    statement = (
        select(ScriptCommandRow)
        .where(ScriptCommandRow.status == ScriptCommandStatus.PENDING.value)
        .order_by(ScriptCommandRow.id)
        .limit(1)
    )
    with Session(get_engine()) as session:
        row = session.scalars(statement).one_or_none()
        return _command(row) if row else None


def settle_command(
    session: Session,
    command_id: int,
    status: ScriptCommandStatus,
    outcome: str,
    now: datetime,
) -> None:
    row = session.get(ScriptCommandRow, command_id)
    if row is not None and row.status == ScriptCommandStatus.PENDING.value:
        row.status = status.value
        row.outcome = outcome
        row.processed_at = _naive(now)


def recent_commands(script_id: str, limit: int) -> list[ScriptCommand]:
    statement = (
        select(ScriptCommandRow)
        .where(ScriptCommandRow.script_id == script_id)
        .order_by(ScriptCommandRow.id.desc())
        .limit(limit)
    )
    with Session(get_engine()) as session:
        return [_command(row) for row in session.scalars(statement).all()]


def add_run(session: Session, script_id: str, trigger: str, now: datetime) -> ScriptRun:
    """A run about to start: written before the process exists, so a crash
    in between leaves a record of it."""
    row = ScriptRunRow(
        id="srn_" + secrets.token_hex(6),
        script_id=script_id,
        status=ScriptRunStatus.RUNNING.value,
        trigger=trigger,
        started_at=_naive(now),
        pid=None,
        stop_reason=None,
        stop_detail=None,
        stop_requested_at=None,
        exit_code=None,
        ended_at=None,
    )
    session.add(row)
    session.flush()
    return _run(row)


def set_pid(session: Session, run_id: str, pid: int) -> None:
    row = session.get(ScriptRunRow, run_id)
    if row is not None:
        row.pid = pid


def request_stop(
    session: Session, run_id: str, reason: ScriptStopReason, detail: str, now: datetime
) -> None:
    """Asked to stop; the first reason given is kept."""
    row = session.get(ScriptRunRow, run_id)
    if row is not None and row.status == ScriptRunStatus.RUNNING.value:
        row.status = ScriptRunStatus.STOPPING.value
        row.stop_reason = reason.value
        row.stop_detail = detail
        row.stop_requested_at = _naive(now)


def end_run(
    session: Session,
    run_id: str,
    reason: ScriptStopReason,
    detail: str,
    exit_code: int | None,
    now: datetime,
) -> ScriptRun | None:
    """None when it had already ended."""
    row = session.get(ScriptRunRow, run_id)
    if row is None or row.status == ScriptRunStatus.ENDED.value:
        return None
    row.status = ScriptRunStatus.ENDED.value
    row.stop_reason = reason.value
    row.stop_detail = detail
    row.exit_code = exit_code
    row.ended_at = _naive(now)
    session.flush()
    return _run(row)


def active_run(session: Session, script_id: str) -> ScriptRun | None:
    """Its run that hasn't ended, if any: there is at most one."""
    statement = select(ScriptRunRow).where(
        ScriptRunRow.script_id == script_id,
        ScriptRunRow.status != ScriptRunStatus.ENDED.value,
    )
    row = session.scalars(statement).first()
    return _run(row) if row else None


def active_runs(session: Session | None = None) -> list[ScriptRun]:
    """In `session` when given: a writer holding the lock sees every run started."""
    statement = (
        select(ScriptRunRow)
        .where(ScriptRunRow.status != ScriptRunStatus.ENDED.value)
        .order_by(ScriptRunRow.started_at)
    )
    if session is not None:
        return [_run(row) for row in session.scalars(statement).all()]
    with Session(get_engine()) as own:
        return [_run(row) for row in own.scalars(statement).all()]


def runs_started_since(script_id: str, since: datetime) -> list[ScriptRun]:
    statement = select(ScriptRunRow).where(
        ScriptRunRow.script_id == script_id, ScriptRunRow.started_at >= _naive(since)
    )
    with Session(get_engine()) as session:
        return [_run(row) for row in session.scalars(statement).all()]


def recent_runs(script_id: str, limit: int) -> list[ScriptRun]:
    statement = (
        select(ScriptRunRow)
        .where(ScriptRunRow.script_id == script_id)
        .order_by(ScriptRunRow.started_at.desc(), ScriptRunRow.id.desc())
        .limit(limit)
    )
    with Session(get_engine()) as session:
        return [_run(row) for row in session.scalars(statement).all()]


def find_run(run_id: str) -> ScriptRun | None:
    with Session(get_engine()) as session:
        row = session.get(ScriptRunRow, run_id)
        return _run(row) if row else None


def _refuse_taken(session: Session, name: str) -> None:
    if session.scalars(select(ScriptRow.id).where(ScriptRow.name == name)).first() is not None:
        raise DuplicateScriptNameError(f"a script named {name!r} already exists")


def _encode_schedule(schedule: ScriptSchedule) -> dict[str, Any]:
    return {
        "version": SCHEDULE_VERSION,
        "start_time": schedule.start_time.isoformat(timespec="minutes"),
        "stop_time": schedule.stop_time.isoformat(timespec="minutes")
        if schedule.stop_time
        else None,
        "weekdays": sorted(schedule.weekdays),
        "exchange": schedule.exchange.value,
    }


def _decode_schedule(data: dict[str, Any]) -> ScriptSchedule:
    if data.get("version") != SCHEDULE_VERSION:
        raise ValueError(f"unknown script schedule version {data.get('version')!r}")
    return ScriptSchedule(
        start_time=time.fromisoformat(data["start_time"]),
        stop_time=time.fromisoformat(data["stop_time"]) if data["stop_time"] else None,
        weekdays=frozenset(data["weekdays"]),
        exchange=Exchange(data["exchange"]),
    )


def _stored(row: ScriptRow) -> StoredScript:
    return StoredScript(
        id=row.id,
        name=row.name,
        source_sha256=row.source_sha256,
        source_bytes=row.source_bytes,
        schedule=_decode_schedule(json.loads(row.schedule)) if row.schedule else None,
        created_at=_aware(row.created_at),
        updated_at=_aware(row.updated_at),
    )


def _command(row: ScriptCommandRow) -> ScriptCommand:
    return ScriptCommand(
        id=row.id,
        script_id=row.script_id,
        kind=ScriptCommandKind(row.kind),
        triggered_by=row.triggered_by,
        status=ScriptCommandStatus(row.status),
        created_at=_aware(row.created_at),
        outcome=row.outcome,
        processed_at=_aware(row.processed_at) if row.processed_at else None,
    )


def _run(row: ScriptRunRow) -> ScriptRun:
    return ScriptRun(
        id=row.id,
        script_id=row.script_id,
        status=ScriptRunStatus(row.status),
        trigger=row.trigger,
        started_at=_aware(row.started_at),
        pid=row.pid,
        stop_reason=ScriptStopReason(row.stop_reason) if row.stop_reason else None,
        stop_detail=row.stop_detail,
        stop_requested_at=_aware(row.stop_requested_at) if row.stop_requested_at else None,
        exit_code=row.exit_code,
        ended_at=_aware(row.ended_at) if row.ended_at else None,
    )


def _naive(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(tzinfo=None)


def _aware(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC)
