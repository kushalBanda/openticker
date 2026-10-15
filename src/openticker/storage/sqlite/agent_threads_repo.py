"""Chats with the user's coding agent (ADR 40 in docs/adr). Each message in
one is an agent job whose `thread_id` names it (agent_jobs_repo)."""

import secrets
from collections.abc import Collection
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import Literal

from sqlalchemy import ColumnElement, and_, func, literal_column, or_, select
from sqlalchemy.orm import Session

from openticker.core.agents.jobs import AgentJob, AgentJobKind, Harness
from openticker.core.agents.threads import Access, AgentThread, Folder
from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.models import AgentJobRow, AgentThreadRow


def add_thread(
    session: Session,
    folder: Folder,
    subject: str | None,
    harness: Harness,
    title: str,
    now: datetime,
    origin_job_id: str | None = None,
    access: Access = Access.TRADE,
) -> AgentThread:
    thread = AgentThread(
        id="thr_" + secrets.token_hex(6),
        title=title,
        folder=folder,
        subject=subject,
        harness=harness,
        session_id=None,
        origin_job_id=origin_job_id,
        created_at=now,
        updated_at=now,
        read_at=now,
        access=access,
    )
    session.add(
        AgentThreadRow(
            id=thread.id,
            title=title,
            folder=folder.value,
            subject=subject,
            harness=harness.value,
            origin_job_id=origin_job_id,
            created_at=_naive(now),
            updated_at=_naive(now),
            read_at=_naive(now),
            access=access.value,
        )
    )
    return thread


def open_job_thread(session: Session, job: AgentJob, title: str, now: datetime) -> AgentJob:
    """A review's or debrief's own thread, opened in the transaction that
    queues it, so its run shows as a chat and can be continued as one. The
    job, now in it."""
    if job.kind is AgentJobKind.REVIEW:
        folder, subject = Folder.REVIEW, job.strategy_id
    elif job.kind is AgentJobKind.DEBRIEF:
        folder, subject = Folder.DEBRIEF, job.subject.isoformat() if job.subject else None
    else:
        raise ValueError(f"a {job.kind} job has no thread of its own")
    thread = add_thread(session, folder, subject, job.harness, title, now, origin_job_id=job.id)
    row = session.get(AgentJobRow, job.id)
    assert row is not None
    row.thread_id = thread.id
    return replace(job, thread_id=thread.id)


def find_thread(thread_id: str, session: Session | None = None) -> AgentThread | None:
    if session is not None:
        row = session.get(AgentThreadRow, thread_id)
        return _thread(row) if row else None
    with Session(get_engine()) as own:
        row = own.get(AgentThreadRow, thread_id)
        return _thread(row) if row else None


def set_session(session: Session, thread_id: str, session_id: str | None) -> None:
    row = session.get(AgentThreadRow, thread_id)
    assert row is not None
    row.session_id = session_id


def mark_deleted(session: Session, thread_id: str, now: datetime) -> None:
    row = session.get(AgentThreadRow, thread_id)
    assert row is not None
    row.deleted_at = _naive(now)


def set_pinned(session: Session, thread_id: str, at: datetime | None) -> None:
    row = session.get(AgentThreadRow, thread_id)
    assert row is not None
    row.pinned_at = _naive(at) if at else None


def set_archived(session: Session, thread_id: str, at: datetime | None) -> None:
    row = session.get(AgentThreadRow, thread_id)
    assert row is not None
    row.archived_at = _naive(at) if at else None


def set_title(session: Session, thread_id: str, title: str) -> None:
    row = session.get(AgentThreadRow, thread_id)
    assert row is not None
    row.title = title


def mark_read(session: Session, thread_id: str, at: datetime) -> None:
    row = session.get(AgentThreadRow, thread_id)
    assert row is not None
    row.read_at = _naive(at)


def touch(session: Session, thread_id: str, now: datetime) -> None:
    row = session.get(AgentThreadRow, thread_id)
    assert row is not None
    row.updated_at = _naive(now)


def recent_threads(limit: int) -> list[AgentThread]:
    """Listed threads not pinned, most recently active first."""
    statement = (
        select(AgentThreadRow)
        .where(_listed(), AgentThreadRow.pinned_at.is_(None))
        .order_by(AgentThreadRow.updated_at.desc())
        .limit(limit)
    )
    with Session(get_engine()) as session:
        return [_thread(row) for row in session.scalars(statement).all()]


def pinned_threads() -> list[AgentThread]:
    """Listed pinned threads, the latest pinned first."""
    statement = (
        select(AgentThreadRow)
        .where(_listed(), AgentThreadRow.pinned_at.is_not(None))
        .order_by(AgentThreadRow.pinned_at.desc())
    )
    with Session(get_engine()) as session:
        return [_thread(row) for row in session.scalars(statement).all()]


def threads_in(folders: Collection[Folder], subject: str | None, limit: int) -> list[AgentThread]:
    """Listed threads in these folders, about `subject` when given, most
    recently active first."""
    statement = select(AgentThreadRow).where(
        _listed(),
        AgentThreadRow.folder.in_([folder.value for folder in folders]),
    )
    if subject is not None:
        statement = statement.where(AgentThreadRow.subject == subject)
    statement = statement.order_by(AgentThreadRow.updated_at.desc()).limit(limit)
    with Session(get_engine()) as session:
        return [_thread(row) for row in session.scalars(statement).all()]


def counts() -> list[tuple[Folder, str | None, int]]:
    """Listed threads by folder and subject."""
    statement = (
        select(AgentThreadRow.folder, AgentThreadRow.subject, func.count())
        .where(_listed())
        .group_by(AgentThreadRow.folder, AgentThreadRow.subject)
    )
    with Session(get_engine()) as session:
        return [
            (Folder(folder), subject, int(n)) for folder, subject, n in session.execute(statement)
        ]


def manager_threads(day: date, session: Session | None = None) -> list[AgentThread]:
    """Every live thread of the desk manager's trading day, oldest first: a
    day whose first turn left no conversation has a second (ADR 41)."""
    statement = (
        select(AgentThreadRow)
        .where(
            AgentThreadRow.deleted_at.is_(None),
            AgentThreadRow.folder == Folder.MANAGER.value,
            AgentThreadRow.subject == day.isoformat(),
        )
        .order_by(AgentThreadRow.created_at, literal_column("rowid"))
    )
    if session is not None:
        return [_thread(row) for row in session.scalars(statement).all()]
    with Session(get_engine()) as own:
        return [_thread(row) for row in own.scalars(statement).all()]


def live_thread_ids() -> set[str]:
    statement = select(AgentThreadRow.id).where(AgentThreadRow.deleted_at.is_(None))
    with Session(get_engine()) as session:
        return set(session.scalars(statement).all())


@dataclass(frozen=True)
class SearchHit:
    thread: AgentThread
    matched: Literal["title", "message", "answer"]
    text: str  # the field that matched, whole
    at: datetime  # when that turn was asked, or the thread last moved for its title


def search(
    text: str, folders: Collection[Folder] | None, archived: bool, limit: int
) -> list[SearchHit]:
    """Chats whose title, one of whose messages, or one of whose answers
    holds `text`, case-blind, the most recently active first: archived ones
    only when `archived`, else only those in the list. Each once, with its
    newest matching message or answer, else its title."""
    wanted = [
        AgentThreadRow.deleted_at.is_(None),
        AgentThreadRow.archived_at.is_not(None)
        if archived
        else AgentThreadRow.archived_at.is_(None),
    ]
    if folders is not None:
        wanted.append(AgentThreadRow.folder.in_([folder.value for folder in folders]))
    turns = (
        select(AgentThreadRow, AgentJobRow)
        .join(AgentJobRow, AgentJobRow.thread_id == AgentThreadRow.id)
        .where(
            *wanted,
            or_(
                AgentJobRow.prompt.icontains(text, autoescape=True),
                AgentJobRow.summary.icontains(text, autoescape=True),
            ),
        )
        .order_by(AgentJobRow.created_at.desc())
    )
    titles = (
        select(AgentThreadRow)
        .where(*wanted, AgentThreadRow.title.icontains(text, autoescape=True))
        .order_by(AgentThreadRow.updated_at.desc())
        .limit(limit)
    )
    hits: dict[str, SearchHit] = {}
    needle = text.lower()
    with Session(get_engine()) as session:
        for thread_row, job in session.execute(turns.limit(limit * 5)):
            if thread_row.id in hits:
                continue
            asked = job.prompt or ""
            matched: Literal["message", "answer"] = (
                "message" if needle in asked.lower() else "answer"
            )
            hits[thread_row.id] = SearchHit(
                _thread(thread_row),
                matched,
                asked if matched == "message" else job.summary or "",
                job.created_at.replace(tzinfo=UTC),
            )
        for thread_row in session.scalars(titles):
            if thread_row.id not in hits:
                thread = _thread(thread_row)
                hits[thread.id] = SearchHit(thread, "title", thread.title, thread.updated_at)
    return sorted(hits.values(), key=lambda hit: hit.thread.updated_at, reverse=True)[:limit]


def _listed() -> ColumnElement[bool]:
    """In the chat list: neither deleted nor archived."""
    return and_(AgentThreadRow.deleted_at.is_(None), AgentThreadRow.archived_at.is_(None))


def _thread(row: AgentThreadRow) -> AgentThread:
    return AgentThread(
        id=row.id,
        title=row.title,
        folder=Folder(row.folder),
        subject=row.subject,
        harness=Harness(row.harness),
        session_id=row.session_id,
        origin_job_id=row.origin_job_id,
        created_at=row.created_at.replace(tzinfo=UTC),
        updated_at=row.updated_at.replace(tzinfo=UTC),
        deleted_at=row.deleted_at.replace(tzinfo=UTC) if row.deleted_at else None,
        pinned_at=_aware(row.pinned_at),
        archived_at=_aware(row.archived_at),
        read_at=_aware(row.read_at),
        access=Access(row.access) if row.access else Access.TRADE,
    )


def _aware(moment: datetime | None) -> datetime | None:
    return moment.replace(tzinfo=UTC) if moment else None


def _naive(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(tzinfo=None)
