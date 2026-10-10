"""The brain's notes and the links between them, and the counts a lesson's
status is derived from.

Links are the server's: structural ones come from the record (a strategy to
the symbols it trades), body ones from the wikilinks in a note's markdown,
re-derived on every write. A link to a day, strategy or symbol makes that
note if it isn't there yet; a link to an unknown lesson or proposal is left
as text.
"""

import json
import secrets
from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from typing import Literal

from sqlalchemy import (
    and_,
    case,
    delete,
    exists,
    func,
    literal,
    null,
    or_,
    select,
    union_all,
    update,
)
from sqlalchemy.orm import Session, aliased

from openticker.core.agents.jobs import AgentJobEndReason, AgentJobKind
from openticker.core.brain.learning import CITE_WINDOW, Design, Review, Use
from openticker.core.brain.lessons import CheckOutcome, Held, Override, Subject, UsePurpose
from openticker.core.brain.notes import (
    NoteKind,
    WrittenBy,
    day_title,
    note_key,
    parse_refs,
    symbol_title,
)
from openticker.ports.models import EXCHANGE_TIMEZONE
from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.models import (
    AgentJobRow,
    BrainLessonCheckRow,
    BrainLessonUseRow,
    BrainLinkRow,
    BrainNoteRow,
    BrainSettingsRow,
    SandboxTradeRow,
    StrategyRow,
    StrategyRunRow,
)

SERVER = "openticker"  # who made the notes OpenTicker makes itself
STRUCTURAL: Literal["structural"] = "structural"
BODY: Literal["body"] = "body"


@dataclass(frozen=True)
class NoteHead:
    """A graph point or a list row."""

    note_id: str
    kind: NoteKind
    key: str
    title: str
    state: str | None  # a proposal's; a lesson's status is derived on read
    strategy_id: str | None
    written_by: WrittenBy
    updated_at: datetime  # tz-aware UTC
    override: Override | None  # a lesson's, set by a person
    reason: str | None  # a rejected proposal's


@dataclass(frozen=True)
class Note(NoteHead):
    body: str
    user_body: str | None
    user_updated_at: datetime | None
    user_updated_by: str | None
    override_at: datetime | None
    override_by: str | None
    override_reason: str | None
    decided_at: datetime | None  # a proposal's latest decision
    decided_by: str | None
    data: Mapping[str, object]
    created_at: datetime
    created_by: str
    updated_by: str
    version: int


@dataclass(frozen=True)
class Link:
    from_id: str
    to_id: str
    origin: Literal["structural", "body"]


@dataclass(frozen=True)
class OwedCheck:
    """A lesson that applies to a run or order, which hasn't been checked
    against it yet."""

    lesson_id: str
    lesson_title: str
    run_id: str | None
    order_id: str | None  # exactly one of the two
    strategy_id: str | None  # None for an order placed outside a strategy
    ended_at: datetime  # the run's end, or the order's last fill


@dataclass(frozen=True)
class LessonCheck:
    """Whether a lesson held on one run or one order outside a strategy."""

    lesson_id: str
    run_id: str | None
    order_id: str | None  # exactly one of the two
    strategy_id: str | None
    ended_at: datetime | None  # the run's end or the order's last fill
    outcome: CheckOutcome
    observed: str | None
    why: str
    checked_by: str
    checked_at: datetime
    reset_at: datetime | None = None  # the paper account was reset after it

    @property
    def subject(self) -> str:
        return f"run:{self.run_id}" if self.run_id else f"order:{self.order_id}"


@dataclass(frozen=True)
class LessonUse:
    lesson_id: str
    purpose: UsePurpose
    strategy_id: str | None
    job_id: str | None
    how: str
    used_by: str
    used_at: datetime


class StaleVersionError(Exception):
    """The note changed since the version an edit started from."""


@dataclass(frozen=True)
class DeskStrategy:
    """A strategy as the brain needs it: its note's title and its symbols."""

    strategy_id: str
    name: str
    symbols: tuple[str, ...]  # EXCHANGE:SYMBOL


@contextmanager
def reading() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session


def new_id(prefix: Literal["les", "prp", "bn"]) -> str:
    return f"{prefix}_{secrets.token_hex(3)}"


def ensure_note(session: Session, kind: NoteKind, key: str, now: datetime) -> NoteHead | None:
    """The day, strategy or symbol note under `key`, made now if missing;
    None for a strategy that doesn't exist, or a lesson or proposal that
    doesn't."""
    row = _find(session, kind, key)
    if row is not None:
        return _head(row)
    if kind in (NoteKind.LESSON, NoteKind.PROPOSAL):
        return None
    if kind is NoteKind.STRATEGY:
        strategy = session.get(StrategyRow, key)
        if strategy is None:
            return None
        title = strategy.name
    elif kind is NoteKind.DAY:
        title = day_title(date.fromisoformat(key))
    else:
        title = symbol_title(key)
    row = _new_row(session, kind, key, title, now)
    session.flush()
    return _head(row)


def write_note(
    session: Session,
    note_id: str | None,
    kind: NoteKind,
    key: str,
    *,
    title: str,
    body: str,
    data: Mapping[str, object],
    state: str | None,
    strategy_id: str | None,
    structural: Iterable[tuple[NoteKind, str]],
    written_by: WrittenBy,
    now: datetime,
    by: str,
    keep: Collection[str] = (),
) -> Note:
    """Writes the agent's part of a note (made if new; the user's part is
    kept, and the `keep` keys of its data), bumps its version and re-derives
    its links."""
    row = session.get(BrainNoteRow, note_id) if note_id else _find(session, kind, key)
    if row is None:
        row = _new_row(session, kind, key, title, now, note_id=note_id)
        row.created_by = by
    old = json.loads(row.data) if row.data else {}
    data = {**data, **{k: old[k] for k in keep if isinstance(old, dict) and k in old}}
    row.title = title
    row.body = body
    row.data = json.dumps(data) if data else None
    row.state = state
    row.strategy_id = strategy_id
    row.written_by = written_by.value
    row.updated_at = _naive(now)
    row.updated_by = by
    row.version += 1
    session.flush()
    _set_structural(session, row.id, structural, now)
    _relink_body(session, row, now)
    return _note(row)


def write_user_body(
    session: Session, note_id: str, text: str | None, expected_version: int, now: datetime, by: str
) -> tuple[Note, str | None] | None:
    """Sets the user's part of a note when it is still at `expected_version`,
    bumps the version and re-derives its body links: the note and the text
    it replaced. None when there's no such note."""
    row = session.get(BrainNoteRow, note_id)
    if row is None:
        return None
    if row.version != expected_version:
        raise StaleVersionError(
            f"the note is at version {row.version}, not {expected_version}: it changed "
            "since you started"
        )
    previous = row.user_body
    row.user_body = text
    row.user_updated_at = _naive(now)
    row.user_updated_by = by
    row.version += 1
    session.flush()
    _relink_body(session, row, now)
    return _note(row), previous


def set_override(
    session: Session,
    lesson_id: str,
    override: Override | None,
    reason: str | None,
    now: datetime,
    by: str,
) -> Note | None:
    """A person's override of a lesson's status, or None to let its checks
    decide. None when there's no such lesson."""
    row = session.get(BrainNoteRow, lesson_id)
    if row is None or row.kind != NoteKind.LESSON:
        return None
    row.override = override.value if override else None
    row.override_at = _naive(now) if override else None
    row.override_by = by if override else None
    row.override_reason = reason if override else None
    row.version += 1
    session.flush()
    return _note(row)


def set_state(
    session: Session, note_id: str, state: str, reason: str | None, now: datetime, by: str
) -> Note | None:
    """A proposal's decision: its state, and the reason when one is given.
    None when there's no such proposal."""
    row = session.get(BrainNoteRow, note_id)
    if row is None or row.kind != NoteKind.PROPOSAL:
        return None
    row.state = state
    row.reason = reason
    row.decided_at = _naive(now)
    row.decided_by = by
    row.version += 1
    session.flush()
    return _note(row)


def run_subject(session: Session, run_id: str) -> Subject | None:
    run = session.get(StrategyRunRow, run_id)
    if run is None:
        return None
    ended = _aware(run.ended_at) if run.ended_at else None
    return Subject(run.id, None, run.strategy_id, ended)


def order_subject(session: Session, order_id: str) -> tuple[Subject, str | None] | None:
    """The order as a check's subject, and the run it was placed for when it
    was a strategy's; None for an order with no fills (or none left after a
    reset)."""
    row = session.execute(
        select(func.max(SandboxTradeRow.filled_at), func.max(SandboxTradeRow.run_id)).where(
            SandboxTradeRow.order_id == order_id
        )
    ).one()
    last, run_id = row
    if last is None:
        return None
    return Subject(None, order_id, None, _aware(last)), run_id


def upsert_check(session: Session, check: LessonCheck) -> LessonCheck | None:
    """Records the check, replacing any earlier one on the same run or
    order: the previous one, or None."""
    row = session.get(BrainLessonCheckRow, (check.lesson_id, check.subject))
    previous = _check(row) if row else None
    if row is None:
        row = BrainLessonCheckRow(lesson_id=check.lesson_id, subject=check.subject)
        session.add(row)
    row.run_id = check.run_id
    row.order_id = check.order_id
    row.strategy_id = check.strategy_id
    row.ended_at = _naive(check.ended_at) if check.ended_at else None
    row.outcome = check.outcome.value
    row.observed = check.observed
    row.why = check.why
    row.checked_by = check.checked_by
    row.checked_at = _naive(check.checked_at)
    row.reset_at = None
    session.flush()
    return previous


def checks_of(session: Session, lesson_id: str, limit: int) -> list[LessonCheck]:
    """A lesson's checks, latest run or order first."""
    rows = session.scalars(
        select(BrainLessonCheckRow)
        .where(BrainLessonCheckRow.lesson_id == lesson_id)
        .order_by(BrainLessonCheckRow.ended_at.desc(), BrainLessonCheckRow.checked_at.desc())
        .limit(limit)
    )
    return [_check(r) for r in rows]


def checks_on(session: Session, subjects: Collection[str]) -> list[tuple[LessonCheck, str]]:
    """The checks given on these runs and orders, with their lessons' titles."""
    rows = session.execute(
        select(BrainLessonCheckRow, BrainNoteRow.title)
        .join(BrainNoteRow, BrainNoteRow.id == BrainLessonCheckRow.lesson_id)
        .where(BrainLessonCheckRow.subject.in_(list(subjects)))
        .order_by(BrainLessonCheckRow.ended_at, BrainNoteRow.title)
    ).all()
    return [(_check(row), title) for row, title in rows]


def add_use(session: Session, use: LessonUse) -> None:
    session.add(
        BrainLessonUseRow(
            lesson_id=use.lesson_id,
            purpose=use.purpose.value,
            strategy_id=use.strategy_id,
            job_id=use.job_id,
            how=use.how,
            used_by=use.used_by,
            used_at=_naive(use.used_at),
        )
    )
    session.flush()


def uses_of(session: Session, lesson_id: str, limit: int) -> tuple[list[LessonUse], int]:
    """A lesson's latest uses, newest first, and how many there are in all."""
    rows = session.scalars(
        select(BrainLessonUseRow)
        .where(BrainLessonUseRow.lesson_id == lesson_id)
        .order_by(BrainLessonUseRow.used_at.desc(), BrainLessonUseRow.id.desc())
        .limit(limit)
    )
    total = session.scalar(select(func.count()).where(BrainLessonUseRow.lesson_id == lesson_id))
    return [
        LessonUse(
            lesson_id=r.lesson_id,
            purpose=UsePurpose(r.purpose),
            strategy_id=r.strategy_id,
            job_id=r.job_id,
            how=r.how,
            used_by=r.used_by,
            used_at=_aware(r.used_at),
        )
        for r in rows
    ], int(total or 0)


def unfrozen_debriefs(session: Session) -> list[str]:
    """The days with a debrief whose record hasn't been frozen by a reset."""
    rows = session.execute(
        select(BrainNoteRow.key, BrainNoteRow.data).where(
            BrainNoteRow.kind == NoteKind.DAY, BrainNoteRow.data.is_not(None)
        )
    ).all()
    days = []
    for key, raw in rows:
        data = json.loads(raw or "{}")
        if isinstance(data, dict) and "headline" in data and "frozen" not in data:
            days.append(key)
    return sorted(days)


def freeze_days(
    session: Session, records: Mapping[str, Mapping[str, object]], reset_at: datetime
) -> int:
    """Keeps each day's record, as it was, in its note's data: a paper
    account reset is about to delete the trades it was read from."""
    frozen = 0
    for key, record in records.items():
        row = _find(session, NoteKind.DAY, key)
        if row is None:
            continue
        data = json.loads(row.data) if row.data else {}
        data["frozen"] = dict(record)
        data["frozen_at"] = reset_at.astimezone(UTC).isoformat()
        row.data = json.dumps(data)
        frozen += 1
    session.flush()
    return frozen


def mark_checks_before_reset(session: Session, reset_at: datetime) -> int:
    """Stamps every check given before a paper account reset. They still count."""
    result = session.execute(
        update(BrainLessonCheckRow)
        .where(BrainLessonCheckRow.reset_at.is_(None))
        .values(reset_at=_naive(reset_at))
    )
    return int(getattr(result, "rowcount", 0) or 0)


def get_debrief_at() -> time | None:
    """When the daily debrief runs, exchange time; None: it doesn't."""
    with Session(get_engine()) as session:
        row = session.get(BrainSettingsRow, 1)
        return time.fromisoformat(row.debrief_at) if row and row.debrief_at else None


def set_debrief_at(session: Session, at: time | None) -> None:
    row = session.get(BrainSettingsRow, 1)
    if row is None:
        row = BrainSettingsRow(id=1)
        session.add(row)
    row.debrief_at = at.strftime("%H:%M") if at else None
    session.flush()


def sync_strategies(desk: Sequence[DeskStrategy], now: datetime) -> None:
    """A note for every strategy and each symbol it trades, linked; renamed
    strategies retitled. Takes the write lock only when something differs,
    and checks again under it: two reads at once make each note once."""
    with Session(get_engine()) as session:
        if not any(_out_of_step(session, strategy) for strategy in desk):
            return
    with Session(get_engine()) as session:
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        _sync(session, desk, now)
        session.commit()


def _out_of_step(session: Session, strategy: DeskStrategy) -> bool:
    row = _find(session, NoteKind.STRATEGY, strategy.strategy_id)
    return (
        row is None
        or row.title != strategy.name
        or _structural_targets(session, row.id) != {(NoteKind.SYMBOL, s) for s in strategy.symbols}
    )


def _sync(session: Session, desk: Sequence[DeskStrategy], now: datetime) -> None:
    for strategy in desk:
        row = _find(session, NoteKind.STRATEGY, strategy.strategy_id)
        if row is None:
            row = _new_row(session, NoteKind.STRATEGY, strategy.strategy_id, strategy.name, now)
        elif row.title != strategy.name:
            row.title = strategy.name
            row.updated_at = _naive(now)
        session.flush()
        want = {(NoteKind.SYMBOL, s) for s in strategy.symbols}
        if _structural_targets(session, row.id) != want:
            _set_structural(session, row.id, want, now)


def get_note(note_id: str) -> Note | None:
    with Session(get_engine()) as session:
        row = session.get(BrainNoteRow, note_id)
        return _note(row) if row else None


def heads(session: Session, note_ids: Collection[str]) -> list[NoteHead]:
    rows = session.scalars(select(BrainNoteRow).where(BrainNoteRow.id.in_(list(note_ids))))
    return [_head(r) for r in rows]


def find_note(kind: NoteKind, key: str) -> Note | None:
    with Session(get_engine()) as session:
        row = _find(session, kind, key)
        return _note(row) if row else None


def graph(since: date | None, limit: int) -> tuple[list[NoteHead], list[Link], bool]:
    """Strategies and symbols always; days from `since` on; lessons and
    proposals changed since then. Newest first, at most `limit`; the flag
    says when more were left out. Links only among the notes returned."""
    statement = select(BrainNoteRow)
    if since is not None:
        start = datetime.combine(since, time(), EXCHANGE_TIMEZONE)
        statement = statement.where(
            or_(
                BrainNoteRow.kind.in_([NoteKind.STRATEGY, NoteKind.SYMBOL]),
                and_(BrainNoteRow.kind == NoteKind.DAY, BrainNoteRow.key >= since.isoformat()),
                and_(
                    BrainNoteRow.kind.in_([NoteKind.LESSON, NoteKind.PROPOSAL]),
                    BrainNoteRow.updated_at >= _naive(start),
                ),
            )
        )
    statement = statement.order_by(BrainNoteRow.updated_at.desc(), BrainNoteRow.id).limit(limit + 1)
    with Session(get_engine()) as session:
        rows = session.scalars(statement).all()
        heads = [_head(r) for r in rows[:limit]]
        ids = [h.note_id for h in heads]
        links = session.scalars(
            select(BrainLinkRow).where(BrainLinkRow.from_id.in_(ids), BrainLinkRow.to_id.in_(ids))
        ).all()
        return heads, _unique_links(links), len(rows) > limit


def search(
    query: str | None, kind: NoteKind | None, strategy_id: str | None, limit: int | None
) -> list[NoteHead]:
    """Notes whose title or text contains `query`, of `kind`, about
    `strategy_id` (its note, notes linked to it, and its proposals); newest
    first."""
    statement = select(BrainNoteRow)
    if query:
        pattern = "%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        statement = statement.where(
            or_(
                BrainNoteRow.title.ilike(pattern, escape="\\"),
                BrainNoteRow.body.ilike(pattern, escape="\\"),
                BrainNoteRow.user_body.ilike(pattern, escape="\\"),
            )
        )
    if kind is not None:
        statement = statement.where(BrainNoteRow.kind == kind)
    if strategy_id is not None:
        own = (
            select(BrainNoteRow.id)
            .where(BrainNoteRow.kind == NoteKind.STRATEGY, BrainNoteRow.key == strategy_id)
            .scalar_subquery()
        )
        statement = statement.where(
            or_(
                BrainNoteRow.id == own,
                BrainNoteRow.strategy_id == strategy_id,
                BrainNoteRow.id.in_(select(BrainLinkRow.from_id).where(BrainLinkRow.to_id == own)),
                BrainNoteRow.id.in_(select(BrainLinkRow.to_id).where(BrainLinkRow.from_id == own)),
            )
        )
    statement = statement.order_by(BrainNoteRow.updated_at.desc(), BrainNoteRow.id)
    if limit is not None:
        statement = statement.limit(limit)
    with Session(get_engine()) as session:
        return [_head(r) for r in session.scalars(statement).all()]


def links_of(note_id: str) -> tuple[list[NoteHead], list[NoteHead]]:
    """The notes this one links to, and the notes that link to it; by title."""
    with Session(get_engine()) as session:
        out = select(BrainLinkRow.to_id).where(BrainLinkRow.from_id == note_id)
        back = select(BrainLinkRow.from_id).where(BrainLinkRow.to_id == note_id)
        by_title = (BrainNoteRow.kind, BrainNoteRow.title)
        return (
            [
                _head(r)
                for r in session.scalars(
                    select(BrainNoteRow).where(BrainNoteRow.id.in_(out)).order_by(*by_title)
                )
            ],
            [
                _head(r)
                for r in session.scalars(
                    select(BrainNoteRow).where(BrainNoteRow.id.in_(back)).order_by(*by_title)
                )
            ],
        )


def local_links(note_id: str) -> list[Link]:
    """In one query, the links among a note and its neighbours (the notes it
    links to and those linking to it), each pair once whatever its origin."""
    near = union_all(
        select(literal(note_id).label("id")),
        select(BrainLinkRow.to_id).where(BrainLinkRow.from_id == note_id),
        select(BrainLinkRow.from_id).where(BrainLinkRow.to_id == note_id),
    ).subquery()
    with Session(get_engine()) as session:
        rows = session.execute(
            select(BrainLinkRow.from_id, BrainLinkRow.to_id, func.min(BrainLinkRow.origin))
            .where(
                BrainLinkRow.from_id.in_(select(near.c.id)),
                BrainLinkRow.to_id.in_(select(near.c.id)),
            )
            .group_by(BrainLinkRow.from_id, BrainLinkRow.to_id)
            .order_by(BrainLinkRow.from_id, BrainLinkRow.to_id)
        ).all()
    return [
        Link(from_id, to_id, STRUCTURAL if origin == STRUCTURAL else BODY)
        for from_id, to_id, origin in rows
    ]


def held_counts(session: Session, lesson_ids: Collection[str] | None) -> dict[str, Held]:
    """Each lesson's counted checks, held ones, and those since its latest
    reinstatement, in one query. Lessons with no checks are absent."""
    counted = BrainLessonCheckRow.outcome != CheckOutcome.NOT_TESTED
    statement = (
        select(
            BrainLessonCheckRow.lesson_id,
            func.sum(case((counted, 1), else_=0)),
            func.sum(case((BrainLessonCheckRow.outcome == CheckOutcome.HELD, 1), else_=0)),
            func.sum(
                case(
                    (
                        and_(
                            counted,
                            BrainNoteRow.override == Override.REINSTATED,
                            BrainLessonCheckRow.checked_at > BrainNoteRow.override_at,
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
        )
        .join(BrainNoteRow, BrainNoteRow.id == BrainLessonCheckRow.lesson_id)
        .group_by(BrainLessonCheckRow.lesson_id)
    )
    if lesson_ids is not None:
        statement = statement.where(BrainLessonCheckRow.lesson_id.in_(list(lesson_ids)))
    return {
        lesson_id: Held(int(checks or 0), int(held or 0), int(since or 0))
        for lesson_id, checks, held, since in session.execute(statement)
    }


@dataclass(frozen=True)
class LearningRecord:
    """What the brain's learning is counted from, since a moment."""

    lessons: list[tuple[str, datetime]]  # every lesson, with when it was written
    designs: list[Design]  # strategies created since, deleted ones too
    reviews: list[Review]  # review jobs that finished since
    uses: list[Use]  # lesson uses since, less the cite window
    checks: list[tuple[str, CheckOutcome]]  # checks given since


def learning_record(session: Session, since: datetime) -> LearningRecord:
    lessons = session.execute(
        select(BrainNoteRow.id, BrainNoteRow.created_at).where(BrainNoteRow.kind == NoteKind.LESSON)
    ).all()
    designs = session.execute(
        select(StrategyRow.id, StrategyRow.created_at, StrategyRow.created_by).where(
            StrategyRow.created_at >= _naive(since)
        )
    ).all()
    reviews = session.execute(
        select(AgentJobRow.strategy_id, AgentJobRow.started_at, AgentJobRow.ended_at).where(
            AgentJobRow.kind == AgentJobKind.REVIEW,
            AgentJobRow.end_reason == AgentJobEndReason.FINISHED,
            AgentJobRow.started_at.is_not(None),
            AgentJobRow.ended_at >= _naive(since),
        )
    ).all()
    uses = session.execute(
        select(
            BrainLessonUseRow.purpose,
            BrainLessonUseRow.strategy_id,
            BrainLessonUseRow.used_by,
            BrainLessonUseRow.used_at,
        ).where(BrainLessonUseRow.used_at >= _naive(since - CITE_WINDOW))
    ).all()
    checks = session.execute(
        select(BrainLessonCheckRow.lesson_id, BrainLessonCheckRow.outcome).where(
            BrainLessonCheckRow.checked_at >= _naive(since)
        )
    ).all()
    return LearningRecord(
        lessons=[(i, _aware(at)) for i, at in lessons],
        designs=[Design(i, _aware(at), by) for i, at, by in designs],
        reviews=[
            Review(s, _aware(start), _aware(end))
            for s, start, end in reviews
            if start is not None and end is not None
        ],
        uses=[Use(UsePurpose(p), s, by, _aware(at)) for p, s, by, at in uses],
        checks=[(i, CheckOutcome(o)) for i, o in checks],
    )


def scope_of(session: Session, lesson_ids: Collection[str]) -> dict[str, frozenset[str]]:
    """The strategy ids each lesson applies to: its structural links to
    strategies. Empty: desk-wide."""
    rows = session.execute(
        select(BrainLinkRow.from_id, BrainNoteRow.key)
        .join(BrainNoteRow, BrainNoteRow.id == BrainLinkRow.to_id)
        .where(
            BrainLinkRow.from_id.in_(list(lesson_ids)),
            BrainLinkRow.origin == STRUCTURAL,
            BrainNoteRow.kind == NoteKind.STRATEGY,
        )
    ).all()
    scopes: dict[str, set[str]] = {lesson_id: set() for lesson_id in lesson_ids}
    for lesson_id, strategy_id in rows:
        scopes[lesson_id].add(strategy_id)
    return {lesson_id: frozenset(ids) for lesson_id, ids in scopes.items()}


def owed_checks(
    session: Session,
    start: datetime | None,
    end: datetime | None,
    lesson_id: str | None = None,
    limit: int | None = None,
) -> list[OwedCheck]:
    """In one query: every run that ended from `start` up to `end`, and every
    order outside a strategy filled then (either bound None: open), against
    every lesson (or only `lesson_id`) that applies to it and was written
    before it ended, less the checks already given. A lesson with no
    strategies applies to runs and orders alike; one with strategies only to
    their runs. Retired lessons are left to the caller, whose status is
    derived."""
    runs = select(
        StrategyRunRow.id.label("run_id"),
        null().label("order_id"),
        StrategyRunRow.strategy_id.label("strategy_id"),
        StrategyRunRow.ended_at.label("ended_at"),
        (literal("run:") + StrategyRunRow.id).label("subject"),
    ).where(StrategyRunRow.ended_at.is_not(None))
    orders = (
        select(
            null().label("run_id"),
            SandboxTradeRow.order_id.label("order_id"),
            null().label("strategy_id"),
            func.max(SandboxTradeRow.filled_at).label("ended_at"),
            (literal("order:") + SandboxTradeRow.order_id).label("subject"),
        )
        .where(SandboxTradeRow.run_id.is_(None))
        .group_by(SandboxTradeRow.order_id)
    )
    if start is not None:
        runs = runs.where(StrategyRunRow.ended_at >= _naive(start))
        orders = orders.where(SandboxTradeRow.filled_at >= _naive(start))
    if end is not None:
        runs = runs.where(StrategyRunRow.ended_at < _naive(end))
        orders = orders.where(SandboxTradeRow.filled_at < _naive(end))
    subjects = union_all(runs, orders).subquery()
    lesson = aliased(BrainNoteRow)
    target = aliased(BrainNoteRow)
    scoped = (
        select(BrainLinkRow.from_id)
        .join(target, target.id == BrainLinkRow.to_id)
        .where(
            BrainLinkRow.from_id == lesson.id,
            BrainLinkRow.origin == STRUCTURAL,
            target.kind == NoteKind.STRATEGY,
        )
    )
    statement = (
        select(
            lesson.id,
            lesson.title,
            subjects.c.run_id,
            subjects.c.order_id,
            subjects.c.strategy_id,
            subjects.c.ended_at,
        )
        .join(subjects, lesson.created_at < subjects.c.ended_at)
        .where(
            lesson.kind == NoteKind.LESSON,
            or_(
                ~exists(scoped),
                exists(scoped.where(target.key == subjects.c.strategy_id)),
            ),
            ~exists(
                select(BrainLessonCheckRow.lesson_id).where(
                    BrainLessonCheckRow.lesson_id == lesson.id,
                    BrainLessonCheckRow.subject == subjects.c.subject,
                )
            ),
        )
        .order_by(subjects.c.ended_at, subjects.c.subject, lesson.created_at, lesson.id)
    )
    if lesson_id is not None:
        statement = statement.where(lesson.id == lesson_id)
    if limit is not None:
        statement = statement.limit(limit)
    return [
        OwedCheck(lesson_id, title, run_id, order_id, strategy_id, _aware(ended_at))
        for lesson_id, title, run_id, order_id, strategy_id, ended_at in session.execute(
            statement
        ).all()
    ]


def _find(session: Session, kind: NoteKind, key: str) -> BrainNoteRow | None:
    return session.scalar(
        select(BrainNoteRow).where(BrainNoteRow.kind == kind, BrainNoteRow.key == key)
    )


def _new_row(
    session: Session,
    kind: NoteKind,
    key: str,
    title: str,
    now: datetime,
    note_id: str | None = None,
) -> BrainNoteRow:
    prefix: Literal["les", "prp", "bn"] = (
        "les" if kind is NoteKind.LESSON else "prp" if kind is NoteKind.PROPOSAL else "bn"
    )
    while note_id is None or session.get(BrainNoteRow, note_id) is not None:
        note_id = new_id(prefix)
    row = BrainNoteRow(
        id=note_id,
        kind=kind.value,
        key=note_id if kind in (NoteKind.LESSON, NoteKind.PROPOSAL) else key,
        title=title,
        body="",
        written_by=WrittenBy.SERVER.value,
        created_at=_naive(now),
        created_by=SERVER,
        updated_at=_naive(now),
        updated_by=SERVER,
        version=0,
    )
    session.add(row)
    return row


def _structural_targets(session: Session, note_id: str) -> set[tuple[NoteKind, str]]:
    rows = session.execute(
        select(BrainNoteRow.kind, BrainNoteRow.key)
        .join(BrainLinkRow, BrainLinkRow.to_id == BrainNoteRow.id)
        .where(BrainLinkRow.from_id == note_id, BrainLinkRow.origin == STRUCTURAL)
    ).all()
    return {(NoteKind(kind), key) for kind, key in rows}


def _set_structural(
    session: Session, note_id: str, targets: Iterable[tuple[NoteKind, str]], now: datetime
) -> None:
    _set_links(session, note_id, STRUCTURAL, targets, now)


def _relink_body(session: Session, row: BrainNoteRow, now: datetime) -> None:
    text = row.body + "\n" + (row.user_body or "")
    refs = [(r.kind, r.key) for r in parse_refs(text) if isinstance(r.kind, NoteKind)]
    _set_links(session, row.id, BODY, refs, now)


def _set_links(
    session: Session,
    note_id: str,
    origin: Literal["structural", "body"],
    targets: Iterable[tuple[NoteKind, str]],
    now: datetime,
) -> None:
    to_ids: set[str] = set()
    for kind, key in targets:
        target = ensure_note(session, kind, note_key(kind, key), now)
        if target is not None and target.note_id != note_id:
            to_ids.add(target.note_id)
    session.execute(
        delete(BrainLinkRow).where(BrainLinkRow.from_id == note_id, BrainLinkRow.origin == origin)
    )
    session.add_all(BrainLinkRow(from_id=note_id, to_id=t, origin=origin) for t in sorted(to_ids))
    session.flush()


def _unique_links(rows: Sequence[BrainLinkRow]) -> list[Link]:
    """One link per pair of notes, whichever way and however it was made;
    structural wins."""
    seen: dict[frozenset[str], Link] = {}
    for row in sorted(rows, key=lambda r: (r.origin != STRUCTURAL, r.from_id, r.to_id)):
        pair = frozenset((row.from_id, row.to_id))
        if pair not in seen:
            seen[pair] = Link(
                row.from_id, row.to_id, STRUCTURAL if row.origin == STRUCTURAL else BODY
            )
    return list(seen.values())


def _head(row: BrainNoteRow) -> NoteHead:
    return NoteHead(
        note_id=row.id,
        kind=NoteKind(row.kind),
        key=row.key,
        title=row.title,
        state=row.state,
        strategy_id=row.strategy_id,
        written_by=WrittenBy(row.written_by),
        updated_at=_aware(row.updated_at),
        override=Override(row.override) if row.override else None,
        reason=row.reason,
    )


def _note(row: BrainNoteRow) -> Note:
    data = json.loads(row.data) if row.data else {}
    return Note(
        note_id=row.id,
        kind=NoteKind(row.kind),
        key=row.key,
        title=row.title,
        state=row.state,
        strategy_id=row.strategy_id,
        written_by=WrittenBy(row.written_by),
        updated_at=_aware(row.updated_at),
        override=Override(row.override) if row.override else None,
        reason=row.reason,
        body=row.body,
        user_body=row.user_body,
        user_updated_at=_aware(row.user_updated_at) if row.user_updated_at else None,
        user_updated_by=row.user_updated_by,
        override_at=_aware(row.override_at) if row.override_at else None,
        override_by=row.override_by,
        override_reason=row.override_reason,
        decided_at=_aware(row.decided_at) if row.decided_at else None,
        decided_by=row.decided_by,
        data=data if isinstance(data, dict) else {},
        created_at=_aware(row.created_at),
        created_by=row.created_by,
        updated_by=row.updated_by,
        version=row.version,
    )


def _check(row: BrainLessonCheckRow) -> LessonCheck:
    return LessonCheck(
        lesson_id=row.lesson_id,
        run_id=row.run_id,
        order_id=row.order_id,
        strategy_id=row.strategy_id,
        ended_at=_aware(row.ended_at) if row.ended_at else None,
        outcome=CheckOutcome(row.outcome),
        observed=row.observed,
        why=row.why,
        checked_by=row.checked_by,
        checked_at=_aware(row.checked_at),
        reset_at=_aware(row.reset_at) if row.reset_at else None,
    )


def _naive(moment: datetime) -> datetime:
    return moment.astimezone(UTC).replace(tzinfo=None)


def _aware(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC)
