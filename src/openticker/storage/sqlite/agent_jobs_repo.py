"""Agent jobs (ADR 29 in docs/adr). MCP and REST add pending jobs; only the
daemon starts, watches and ends them.

A desk job (a debrief) has no strategy: it is stored with strategy_id '',
since that column is NOT NULL and isn't changed (ADR 18), and read back as
None."""

import secrets
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, date, datetime

from sqlalchemy import ColumnElement, func, literal_column, or_, select, true
from sqlalchemy.orm import Session

from openticker.core.agents.jobs import (
    AgentJob,
    AgentJobEndReason,
    AgentJobKind,
    AgentJobStatus,
    Harness,
)
from openticker.ports.agent_job_port import AgentOutcome
from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.models import AgentJobRow

_ACTIVE = (AgentJobStatus.RUNNING.value, AgentJobStatus.STOPPING.value)
_DESK = ""  # a desk job's strategy_id


def add_job(
    session: Session,
    kind: AgentJobKind,
    strategy_id: str | None,
    harness: Harness,
    trigger: str,
    now: datetime,
    subject: date | None = None,
    *,
    thread_id: str | None = None,
    prompt: str | None = None,
    model: str | None = None,
    effort: str | None = None,
) -> AgentJob:
    job = AgentJob(
        id="job_" + secrets.token_hex(6),
        kind=kind,
        strategy_id=strategy_id,
        harness=harness,
        status=AgentJobStatus.PENDING,
        trigger=trigger,
        created_at=now,
        subject=subject,
        thread_id=thread_id,
        prompt=prompt,
        model=model,
        effort=effort,
    )
    session.add(
        AgentJobRow(
            id=job.id,
            kind=kind.value,
            strategy_id=strategy_id or _DESK,
            harness=harness.value,
            status=job.status.value,
            trigger=trigger,
            created_at=_naive(now),
            subject=subject,
            thread_id=thread_id,
            prompt=prompt,
            model=model,
            effort=effort,
        )
    )
    return job


def debrief_for(session: Session, trading_date: date) -> AgentJob | None:
    """The day's newest debrief job that wasn't refused, open or ended."""
    row = session.scalars(
        select(AgentJobRow)
        .where(
            AgentJobRow.kind == AgentJobKind.DEBRIEF.value,
            AgentJobRow.subject == trading_date,
            or_(
                AgentJobRow.end_reason.is_(None),
                AgentJobRow.end_reason != AgentJobEndReason.REFUSED.value,
            ),
        )
        .order_by(AgentJobRow.created_at.desc(), literal_column("rowid").desc())
    ).first()
    return _job(row) if row else None


def open_debrief(session: Session) -> AgentJob | None:
    """A debrief job pending or running, of any day."""
    row = session.scalars(
        select(AgentJobRow).where(
            AgentJobRow.kind == AgentJobKind.DEBRIEF.value,
            AgentJobRow.status != AgentJobStatus.ENDED.value,
        )
    ).first()
    return _job(row) if row else None


def open_job_of(session: Session, strategy_id: str) -> AgentJob | None:
    """Its job that is pending or running, if any."""
    row = session.scalars(
        select(AgentJobRow).where(
            AgentJobRow.kind == AgentJobKind.REVIEW.value,
            AgentJobRow.strategy_id == strategy_id,
            AgentJobRow.status != AgentJobStatus.ENDED.value,
        )
    ).first()
    return _job(row) if row else None


def last_asked_at(strategy_id: str) -> datetime | None:
    """When its newest job was asked for, however it went, leaving out one
    refused before it started: that was no review."""
    statement = select(func.max(AgentJobRow.created_at)).where(
        AgentJobRow.kind == AgentJobKind.REVIEW.value,
        AgentJobRow.strategy_id == strategy_id,
        or_(
            AgentJobRow.end_reason.is_(None),
            AgentJobRow.end_reason != AgentJobEndReason.REFUSED.value,
        ),
    )
    with Session(get_engine()) as session:
        latest = session.scalar(statement)
    return latest.replace(tzinfo=UTC) if latest is not None else None


# Background jobs (reviews, debriefs) and chat turns run in separate lanes
# (ADR 40): the day's cap and one-at-a-time are the background lane's.
_BACKGROUND = AgentJobRow.kind != AgentJobKind.CHAT.value
_CHAT = AgentJobRow.kind == AgentJobKind.CHAT.value


def pending_count(session: Session) -> int:
    """Background jobs waiting."""
    statement = select(func.count()).where(
        AgentJobRow.status == AgentJobStatus.PENDING.value, _BACKGROUND
    )
    return int(session.scalar(statement) or 0)


def started_since(session: Session, since: datetime) -> int:
    """Background jobs that started running at or after `since`."""
    statement = select(func.count()).where(AgentJobRow.started_at >= _naive(since), _BACKGROUND)
    return int(session.scalar(statement) or 0)


def next_pending(session: Session) -> AgentJob | None:
    """The background job asked for first."""
    return _first_pending(session, _BACKGROUND)


def next_pending_chat(session: Session) -> AgentJob | None:
    """The chat turn asked for first whose chat has no turn running: a message
    waiting behind its own chat's turn holds up no other chat (ADR 40)."""
    busy = select(AgentJobRow.thread_id).where(
        AgentJobRow.status.in_(_ACTIVE), AgentJobRow.thread_id.is_not(None)
    )
    return _first_pending(session, _CHAT & AgentJobRow.thread_id.not_in(busy))


def _first_pending(session: Session, lane: ColumnElement[bool]) -> AgentJob | None:
    row = session.scalars(
        select(AgentJobRow)
        .where(AgentJobRow.status == AgentJobStatus.PENDING.value, lane)
        .order_by(AgentJobRow.created_at, literal_column("rowid"))  # first asked, first run
    ).first()
    return _job(row) if row else None


def set_prompt(session: Session, job_id: str, prompt: str) -> bool:
    """Rewrites a waiting turn's message; False once the daemon took it."""
    row = session.get(AgentJobRow, job_id)
    if row is None or row.status != AgentJobStatus.PENDING.value:
        return False
    row.prompt = prompt
    return True


def active_jobs(session: Session | None = None) -> list[AgentJob]:
    """Running or stopping, in either lane."""
    return _active(session, true())


def active_background(session: Session | None = None) -> list[AgentJob]:
    return _active(session, _BACKGROUND)


def active_chat_turns(session: Session | None = None) -> list[AgentJob]:
    return _active(session, _CHAT)


def _active(session: Session | None, lane: ColumnElement[bool]) -> list[AgentJob]:
    statement = select(AgentJobRow).where(AgentJobRow.status.in_(_ACTIVE), lane)
    if session is not None:
        return [_job(row) for row in session.scalars(statement).all()]
    with Session(get_engine()) as own:
        return [_job(row) for row in own.scalars(statement).all()]


def turns_of(thread_id: str, session: Session | None = None) -> list[AgentJob]:
    """A thread's jobs, first asked first."""
    statement = (
        select(AgentJobRow)
        .where(AgentJobRow.thread_id == thread_id)
        .order_by(AgentJobRow.created_at, literal_column("rowid"))
    )
    if session is not None:
        return [_job(row) for row in session.scalars(statement).all()]
    with Session(get_engine()) as own:
        return [_job(row) for row in own.scalars(statement).all()]


def thread_job_ids(live_threads: Iterable[str]) -> set[str]:
    """The ids of every job in these threads."""
    wanted = list(live_threads)
    if not wanted:
        return set()
    statement = select(AgentJobRow.id).where(AgentJobRow.thread_id.in_(wanted))
    with Session(get_engine()) as session:
        return set(session.scalars(statement).all())


def mark_outcome(session: Session, job_id: str, outcome: AgentOutcome) -> None:
    """What ran, as the harness reported it (ADR 40)."""
    row = session.get(AgentJobRow, job_id)
    assert row is not None
    row.session_id = outcome.session_id
    row.model_used = outcome.model_used
    row.input_tokens, row.output_tokens = outcome.input_tokens, outcome.output_tokens
    row.duration_ms = outcome.duration_ms


def mark_running(session: Session, job_id: str, pid: int, now: datetime) -> None:
    row = session.get(AgentJobRow, job_id)
    assert row is not None
    row.status, row.pid, row.started_at = AgentJobStatus.RUNNING.value, pid, _naive(now)


def mark_started(session: Session, job_id: str, now: datetime) -> None:
    """Counts against the day's cap from the moment a start is tried."""
    row = session.get(AgentJobRow, job_id)
    assert row is not None
    row.started_at = _naive(now)


def request_stop(
    session: Session, job_id: str, reason: AgentJobEndReason, detail: str, now: datetime
) -> None:
    row = session.get(AgentJobRow, job_id)
    assert row is not None
    if row.status == AgentJobStatus.RUNNING.value:
        row.status = AgentJobStatus.STOPPING.value
        row.end_reason, row.end_detail = reason.value, detail
        row.stop_requested_at = _naive(now)


def end_job(
    session: Session,
    job_id: str,
    reason: AgentJobEndReason,
    detail: str,
    now: datetime,
    exit_code: int | None = None,
    summary: str | None = None,
    cost_usd: float | None = None,
) -> AgentJob | None:
    """None when it had already ended."""
    row = session.get(AgentJobRow, job_id)
    if row is None or row.status == AgentJobStatus.ENDED.value:
        return None
    row.status = AgentJobStatus.ENDED.value
    row.end_reason, row.end_detail = reason.value, detail
    row.exit_code, row.summary, row.cost_usd = exit_code, summary, cost_usd
    row.ended_at = _naive(now)
    return _job(row)


def find_job(job_id: str) -> AgentJob | None:
    with Session(get_engine()) as session:
        row = session.get(AgentJobRow, job_id)
        return _job(row) if row else None


def runs_without_model(since: datetime) -> tuple[int, int]:
    """Of the runs started since `since` that have ended, chats and
    background jobs alike: how many have no model recorded, and how many
    there are (ADR 40). A run stopped before it started never ran."""
    ran = (
        AgentJobRow.started_at >= _naive(since),
        AgentJobRow.status == AgentJobStatus.ENDED.value,
    )
    missing = select(func.count()).where(*ran, AgentJobRow.model_used.is_(None))
    with Session(get_engine()) as session:
        return (
            int(session.scalar(missing) or 0),
            int(session.scalar(select(func.count()).where(*ran)) or 0),
        )


def recent_jobs(limit: int, strategy_id: str | None = None) -> list[AgentJob]:
    """Background jobs, newest first: a chat's turns are read with their thread."""
    statement = (
        select(AgentJobRow)
        .where(_BACKGROUND)
        .order_by(AgentJobRow.created_at.desc(), literal_column("rowid").desc())
    )
    if strategy_id is not None:
        statement = statement.where(AgentJobRow.strategy_id == strategy_id)
    with Session(get_engine()) as session:
        return [_job(row) for row in session.scalars(statement.limit(limit)).all()]


def _job(row: AgentJobRow) -> AgentJob:
    job = AgentJob(
        id=row.id,
        kind=AgentJobKind(row.kind),
        strategy_id=row.strategy_id or None,
        harness=Harness(row.harness),
        status=AgentJobStatus(row.status),
        trigger=row.trigger,
        created_at=row.created_at.replace(tzinfo=UTC),
    )
    return replace(
        job,
        started_at=_aware(row.started_at),
        pid=row.pid,
        stop_requested_at=_aware(row.stop_requested_at),
        end_reason=AgentJobEndReason(row.end_reason) if row.end_reason else None,
        end_detail=row.end_detail,
        exit_code=row.exit_code,
        ended_at=_aware(row.ended_at),
        summary=row.summary,
        cost_usd=row.cost_usd,
        subject=row.subject,
        thread_id=row.thread_id,
        prompt=row.prompt,
        model=row.model,
        effort=row.effort,
        model_used=row.model_used,
        session_id=row.session_id,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        duration_ms=row.duration_ms,
    )


def _aware(moment: datetime | None) -> datetime | None:
    return moment.replace(tzinfo=UTC) if moment is not None else None


def _naive(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(tzinfo=None)


def latest_answers() -> dict[str, AgentJob]:
    """Each strategy's newest ended job that answered, by strategy id."""
    statement = (
        select(AgentJobRow)
        .where(
            AgentJobRow.kind == AgentJobKind.REVIEW.value,
            AgentJobRow.status == AgentJobStatus.ENDED.value,
            AgentJobRow.summary.is_not(None),
        )
        .order_by(AgentJobRow.ended_at.desc(), literal_column("rowid").desc())
    )
    newest: dict[str, AgentJob] = {}
    with Session(get_engine()) as session:
        for row in session.scalars(statement):
            newest.setdefault(row.strategy_id, _job(row))
    return newest
