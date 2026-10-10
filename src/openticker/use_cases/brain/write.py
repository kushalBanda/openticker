"""Writing the brain. Each write is one transaction under SQLite's write
lock, then an event (ADR 10), so the audit log says who wrote what and the
web app hears of it as it happens."""

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy.orm import Session

from openticker.core.brain.lessons import (
    MAX_APPLIES_TO,
    NO_CHECKS,
    CheckOutcome,
    Held,
    LessonStatus,
    Override,
    Subject,
    UsePurpose,
    lesson_status,
    parse_evidence,
    validate_check,
    validate_lesson,
    why_not_counted,
)
from openticker.core.brain.notes import (
    MAX_BODY,
    MAX_LINE,
    BrainNoteError,
    Debrief,
    FactKind,
    NoteKind,
    Ref,
    day_title,
    validate_debrief,
    written_by_of,
)
from openticker.core.brain.proposals import (
    Decision,
    Proposal,
    ProposalState,
    decide,
    validate_proposal,
)
from openticker.core.calendar.models import MarketCalendar
from openticker.events.bus import EventPublisher
from openticker.events.types import (
    BrainNoteEdited,
    DebriefWritten,
    LessonStatusChanged,
    LessonWritten,
    ProposalDecided,
    ProposalRaised,
)
from openticker.storage.sqlite import brain_repo, runs_repo
from openticker.storage.sqlite.brain_repo import LessonCheck, LessonUse, Note
from openticker.storage.sqlite.strategies_repo import load_strategy, write_transaction
from openticker.use_cases.brain.read import (
    NoteView,
    UnknownNoteError,
    check_trading_day,
    get_note,
    subjects_of_day,
)


def write_debrief(
    debrief: Debrief,
    events: EventPublisher,
    now: datetime,
    calendar: MarketCalendar,
    triggered_by: str,
) -> NoteView:
    """The day's note with the agent's account of it. Writing again replaces
    the account; the user's own note on the day is kept. Trade notes must be
    about the day's runs and orders. The note links to the strategies that
    ran and the symbols traded outside them."""
    debrief = validate_debrief(debrief)
    check_trading_day(debrief.trading_date, now, calendar)
    trades = subjects_of_day(debrief.trading_date)
    subjects = {t.subject for t in trades}
    for trade_note in debrief.trade_notes:
        if trade_note.subject not in subjects:
            raise BrainNoteError(
                f"{trade_note.subject.replace(':', ' ')} isn't one of {debrief.trading_date}'s runs or "
                "orders placed outside a strategy; get_day_record lists them"
            )
    structural = {(NoteKind.STRATEGY, t.strategy_id) for t in trades if t.run_id and t.strategy_id}
    structural |= {
        (NoteKind.SYMBOL, f"{f.exchange}:{f.symbol}") for t in trades if t.order_id for f in t.fills
    }
    with write_transaction() as session:
        note = brain_repo.write_note(
            session,
            None,
            NoteKind.DAY,
            debrief.trading_date.isoformat(),
            title=day_title(debrief.trading_date),
            body=debrief.happened,
            data={
                "headline": debrief.headline,
                "trade_notes": [
                    {
                        **({"run_id": n.run_id} if n.run_id else {"order_id": n.order_id}),
                        "why": n.why,
                        "trade_off": n.trade_off,
                    }
                    for n in debrief.trade_notes
                ],
                "hindsight": [
                    {"text": h.text, "knowable_before": h.knowable_before}
                    for h in debrief.hindsight
                ],
            },
            state=None,
            strategy_id=None,
            structural=sorted(structural),
            written_by=written_by_of(triggered_by),
            now=now,
            by=triggered_by,
            keep=("frozen", "frozen_at"),
        )
    events.publish(
        DebriefWritten(
            trading_date=debrief.trading_date,
            note_id=note.note_id,
            headline=debrief.headline,
            triggered_by=triggered_by,
            occurred_at=now,
        )
    )
    return get_note(note.note_id)


def edit_user_note(
    note_id: str,
    text: str,
    expected_version: int,
    events: EventPublisher,
    now: datetime,
    triggered_by: str,
) -> NoteView:
    """The user's own part of a note, set when the note is still at
    `expected_version` (StaleVersionError otherwise: someone wrote since).
    Blank clears it. Unchanged text changes nothing."""
    cleaned = text.strip() or None
    if cleaned is not None and len(cleaned) > MAX_BODY:
        raise BrainNoteError(f"your note is {len(cleaned):,} characters; at most {MAX_BODY:,}")
    current = brain_repo.get_note(note_id)
    if current is None:
        raise UnknownNoteError(f"no note {note_id}")
    if current.user_body == cleaned:
        return get_note(note_id)
    with write_transaction() as session:
        written = brain_repo.write_user_body(
            session, note_id, cleaned, expected_version, now, triggered_by
        )
    if written is None:
        raise UnknownNoteError(f"no note {note_id}")
    note, previous = written
    events.publish(
        BrainNoteEdited(
            note_id=note.note_id,
            kind=note.kind.value,
            title=note.title,
            previous=previous,
            triggered_by=triggered_by,
            occurred_at=now,
        )
    )
    return get_note(note_id)


def create_lesson(
    title: str,
    body: str,
    applies_to: Sequence[str],
    evidence: Sequence[str],
    events: EventPublisher,
    now: datetime,
    triggered_by: str,
) -> NoteView:
    """A new lesson, a hunch until its checks say more. It applies to the
    strategies in `applies_to`, or to the whole desk when that's empty, and
    links to the days, runs and orders it came from."""
    title, body = validate_lesson(title, body)
    scope = _scope(applies_to)
    refs = parse_evidence(evidence)
    _check_facts_exist(refs)
    with write_transaction() as session:
        _check_strategies_exist(session, scope)
        note = brain_repo.write_note(
            session,
            None,
            NoteKind.LESSON,
            "",
            title=title,
            body=body,
            data={"evidence": [f"{r.kind.value}:{r.key}" for r in refs]},
            state=None,
            strategy_id=None,
            structural=_lesson_links(scope, refs),
            written_by=written_by_of(triggered_by),
            now=now,
            by=triggered_by,
        )
    events.publish(
        LessonWritten(
            lesson_id=note.note_id,
            title=title,
            change="created",
            triggered_by=triggered_by,
            occurred_at=now,
        )
    )
    return get_note(note.note_id)


def update_lesson(
    lesson_id: str,
    title: str | None,
    body: str | None,
    applies_to: Sequence[str] | None,
    events: EventPublisher,
    now: datetime,
    triggered_by: str,
) -> NoteView:
    """A lesson's title, text or scope; whatever is None stays. Its checks
    and status are the server's and don't change here."""
    current = _lesson(lesson_id)
    evidence = current.data.get("evidence")
    refs = parse_evidence([str(e) for e in evidence]) if isinstance(evidence, list) else ()
    title, body = validate_lesson(
        current.title if title is None else title, current.body if body is None else body
    )
    with write_transaction() as session:
        if applies_to is None:
            scope = brain_repo.scope_of(session, [lesson_id])[lesson_id]
        else:
            scope = _scope(applies_to)
            _check_strategies_exist(session, scope)
        note = brain_repo.write_note(
            session,
            lesson_id,
            NoteKind.LESSON,
            lesson_id,
            title=title,
            body=body,
            data=dict(current.data),
            state=None,
            strategy_id=None,
            structural=_lesson_links(scope, refs),
            written_by=written_by_of(triggered_by),
            now=now,
            by=triggered_by,
        )
    events.publish(
        LessonWritten(
            lesson_id=note.note_id,
            title=title,
            change="edited",
            triggered_by=triggered_by,
            occurred_at=now,
        )
    )
    return get_note(lesson_id)


def check_lesson(
    lesson_id: str,
    run_id: str | None,
    order_id: str | None,
    outcome: CheckOutcome,
    observed: str | None,
    why: str,
    events: EventPublisher,
    now: datetime,
    triggered_by: str,
) -> tuple[NoteView, LessonCheck, LessonCheck | None]:
    """Whether the lesson held on one ended run, or one order placed outside
    a strategy, that ended after it was written and is in its scope. A
    second answer on the same one replaces the first. Publishes
    LessonStatusChanged when the lesson's status moves. The lesson, the
    check, and the answer it replaced."""
    run_id, order_id = (run_id or "").strip() or None, (order_id or "").strip() or None
    if bool(run_id) == bool(order_id):
        raise BrainNoteError(
            "a check is about a run (run_id) or an order placed outside a strategy "
            "(order_id): give exactly one"
        )
    observed, why = validate_check(outcome, observed, why)
    lesson = _lesson(lesson_id)
    with write_transaction() as session:
        subject = _subject(session, run_id, order_id)
        scope = brain_repo.scope_of(session, [lesson_id])[lesson_id]
        refused = why_not_counted(subject, lesson.created_at, scope)
        if refused is not None:
            raise BrainNoteError(refused)
        before = _held(session, lesson_id)
        check = LessonCheck(
            lesson_id=lesson_id,
            run_id=subject.run_id,
            order_id=subject.order_id,
            strategy_id=subject.strategy_id,
            ended_at=subject.ended_at,
            outcome=outcome,
            observed=observed,
            why=why,
            checked_by=triggered_by,
            checked_at=now,
        )
        previous = brain_repo.upsert_check(session, check)
        after = _held(session, lesson_id)
    _status_moved(lesson, before, after, lesson.override, events, now, triggered_by)
    return get_note(lesson_id), check, previous


def record_lesson_use(
    lesson_id: str,
    purpose: UsePurpose,
    strategy_id: str | None,
    how: str,
    job_id: str | None,
    now: datetime,
    triggered_by: str,
) -> LessonUse:
    """That an agent relied on the lesson, for what and how. Not audited one
    by one: the row says who and when."""
    how = how.strip()
    if not how:
        raise BrainNoteError("say how the lesson was used, in one line")
    if len(how) > MAX_LINE:
        raise BrainNoteError(f"`how` is {len(how):,} characters; at most {MAX_LINE:,}")
    _lesson(lesson_id)
    strategy_id = (strategy_id or "").strip() or None
    use = LessonUse(
        lesson_id=lesson_id,
        purpose=purpose,
        strategy_id=strategy_id,
        job_id=job_id,
        how=how,
        used_by=triggered_by,
        used_at=now,
    )
    with write_transaction() as session:
        if strategy_id is not None:
            _check_strategies_exist(session, frozenset({strategy_id}))
        brain_repo.add_use(session, use)
    return use


def set_lesson_override(
    lesson_id: str,
    override: Override | None,
    reason: str | None,
    events: EventPublisher,
    now: datetime,
    triggered_by: str,
) -> NoteView:
    """A person's say over a lesson's status: retired (with a reason) keeps
    agents from relying on it whatever its checks; reinstated lets its
    checks decide again, with no automatic retirement for the next few
    checks; None clears either. Setting what's already set changes nothing."""
    reason = (reason or "").strip() or None
    if override is Override.RETIRED and reason is None:
        raise BrainNoteError("say why the lesson is retired: agents read the reason")
    if reason is not None and len(reason) > MAX_LINE:
        raise BrainNoteError(f"the reason is {len(reason):,} characters; at most {MAX_LINE:,}")
    lesson = _lesson(lesson_id)
    if override is lesson.override and (override is None or reason == lesson.override_reason):
        return get_note(lesson_id)
    with write_transaction() as session:
        held = _held(session, lesson_id)
        if (
            override is Override.REINSTATED
            and lesson_status(held, lesson.override) is not LessonStatus.RETIRED
        ):
            raise BrainNoteError("the lesson isn't retired; there's nothing to reinstate")
        brain_repo.set_override(session, lesson_id, override, reason, now, triggered_by)
    after = Held(held.checks, held.held, 0) if override is Override.REINSTATED else held
    previous = lesson_status(held, lesson.override)
    status = lesson_status(after, override)
    events.publish(
        LessonStatusChanged(
            lesson_id=lesson_id,
            title=lesson.title,
            previous=previous.value,
            status=status.value,
            held=after.held,
            checks=after.checks,
            triggered_by=triggered_by,
            override=override.value if override else None,
            reason=reason,
            occurred_at=now,
        )
    )
    return get_note(lesson_id)


def raise_proposal(
    proposal: Proposal, events: EventPublisher, now: datetime, triggered_by: str
) -> NoteView:
    """One change to one strategy, for the user to accept or reject. It
    links to the strategy and to the lessons it rests on. Deciding is the
    user's alone."""
    proposal = validate_proposal(proposal)
    with write_transaction() as session:
        _check_strategies_exist(session, frozenset({proposal.strategy_id}))
        lessons = brain_repo.heads(session, proposal.based_on) if proposal.based_on else []
        found = {h.note_id for h in lessons if h.kind is NoteKind.LESSON}
        for lesson_id in proposal.based_on:
            if lesson_id not in found:
                raise BrainNoteError(f"no lesson {lesson_id}; search_brain(kind=lesson) finds them")
        note = brain_repo.write_note(
            session,
            None,
            NoteKind.PROPOSAL,
            "",
            title=proposal.change,
            body=proposal.why,
            data={
                "change": proposal.change,
                "wrong_if": proposal.wrong_if,
                "based_on": list(proposal.based_on),
            },
            state=ProposalState.OPEN.value,
            strategy_id=proposal.strategy_id,
            structural=[(NoteKind.STRATEGY, proposal.strategy_id)]
            + [(NoteKind.LESSON, lesson_id) for lesson_id in proposal.based_on],
            written_by=written_by_of(triggered_by),
            now=now,
            by=triggered_by,
        )
    events.publish(
        ProposalRaised(
            proposal_id=note.note_id,
            strategy_id=proposal.strategy_id,
            change=proposal.change,
            triggered_by=triggered_by,
            occurred_at=now,
        )
    )
    return get_note(note.note_id)


def decide_proposal(
    proposal_id: str,
    decision: Decision,
    reason: str | None,
    events: EventPublisher,
    now: datetime,
    triggered_by: str,
) -> NoteView:
    """Accept (the page then gives the request to paste into an agent),
    reject with a reason (kept, and served to agents with the proposal), or
    put off. Accepted and rejected are final."""
    reason = (reason or "").strip() or None
    with write_transaction() as session:  # the state is read under the write lock
        found = brain_repo.heads(session, [proposal_id])
        current = found[0] if found else None
        if current is None or current.kind is not NoteKind.PROPOSAL:
            raise UnknownNoteError(
                f"no proposal {proposal_id}; search_brain(kind=proposal) finds them"
            )
        state = decide(ProposalState(current.state or ProposalState.OPEN), decision, reason)
        brain_repo.set_state(session, proposal_id, state.value, reason, now, triggered_by)
    events.publish(
        ProposalDecided(
            proposal_id=proposal_id,
            strategy_id=current.strategy_id or "",
            change=current.title,
            decision=decision.value,
            reason=reason,
            triggered_by=triggered_by,
            occurred_at=now,
        )
    )
    return get_note(proposal_id)


def _lesson(lesson_id: str) -> Note:
    note = brain_repo.get_note(lesson_id)
    if note is None or note.kind is not NoteKind.LESSON:
        raise UnknownNoteError(f"no lesson {lesson_id}; search_brain(kind=lesson) finds them")
    return note


def _held(session: Session, lesson_id: str) -> Held:
    return brain_repo.held_counts(session, [lesson_id]).get(lesson_id, NO_CHECKS)


def _status_moved(
    lesson: Note,
    before: Held,
    after: Held,
    override: Override | None,
    events: EventPublisher,
    now: datetime,
    triggered_by: str,
) -> None:
    previous, status = lesson_status(before, override), lesson_status(after, override)
    if previous is status:
        return
    events.publish(
        LessonStatusChanged(
            lesson_id=lesson.note_id,
            title=lesson.title,
            previous=previous.value,
            status=status.value,
            held=after.held,
            checks=after.checks,
            triggered_by=triggered_by,
            override=override.value if override else None,
            occurred_at=now,
        )
    )


def _subject(session: Session, run_id: str | None, order_id: str | None) -> Subject:
    if run_id is not None:
        subject = brain_repo.run_subject(session, run_id)
        if subject is None:
            raise BrainNoteError(f"no run {run_id}; get_day_record lists a day's runs")
        return subject
    assert order_id is not None
    found = brain_repo.order_subject(session, order_id)
    if found is None:
        raise BrainNoteError(
            f"no filled order {order_id}; get_day_record lists the orders placed outside a strategy"
        )
    subject, run = found
    if run is not None:
        raise BrainNoteError(f"order {order_id} is part of run {run}: check the run instead")
    return subject


def _scope(applies_to: Sequence[str]) -> frozenset[str]:
    scope = frozenset(s.strip() for s in applies_to if s.strip())
    if len(scope) > MAX_APPLIES_TO:
        raise BrainNoteError(f"a lesson applies to at most {MAX_APPLIES_TO} strategies")
    return scope


def _check_strategies_exist(session: Session, scope: frozenset[str]) -> None:
    for strategy_id in sorted(scope):
        if load_strategy(session, strategy_id) is None:
            raise BrainNoteError(f"no strategy {strategy_id}; list_strategies lists them")


def _check_facts_exist(refs: Sequence[Ref]) -> None:
    with brain_repo.reading() as session:
        for ref in refs:
            if ref.kind is FactKind.RUN and runs_repo.find_run(ref.key) is None:
                raise BrainNoteError(f"no run {ref.key} for the evidence")
            if ref.kind is FactKind.ORDER and brain_repo.order_subject(session, ref.key) is None:
                raise BrainNoteError(f"no filled order {ref.key} for the evidence")


def _lesson_links(scope: frozenset[str], refs: Sequence[Ref]) -> list[tuple[NoteKind, str]]:
    """A lesson links to the strategies it applies to and the days it came from."""
    days = [r.key for r in refs if r.kind is NoteKind.DAY]
    return sorted({(NoteKind.STRATEGY, s) for s in scope} | {(NoteKind.DAY, d) for d in days})
