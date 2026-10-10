import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from openticker.composition import build_event_bus
from openticker.core.brain.lessons import CheckOutcome, Held, Override, UsePurpose
from openticker.core.brain.notes import (
    BrainNoteError,
    Debrief,
    Hindsight,
    NoteKind,
    TradeNote,
    WrittenBy,
)
from openticker.core.brain.proposals import Decision, Proposal
from openticker.core.calendar.models import MarketCalendar
from openticker.core.strategies.runs import Run, RunStatus
from openticker.events.types import (
    BrainNoteEdited,
    DebriefWritten,
    LessonStatusChanged,
    LessonWritten,
    ProposalDecided,
    ProposalRaised,
)
from openticker.ports.models import Product, Side
from openticker.storage.sqlite import brain_repo, runs_repo
from openticker.storage.sqlite.audit_repo import list_audit
from openticker.storage.sqlite.brain_repo import StaleVersionError
from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.models import SandboxTradeRow
from openticker.storage.sqlite.strategies_repo import insert_strategy, write_transaction
from openticker.use_cases.brain.read import (
    UnknownNoteError,
    get_day_record,
    get_note,
    search_brain,
)
from openticker.use_cases.brain.write import (
    check_lesson,
    create_lesson,
    decide_proposal,
    edit_user_note,
    raise_proposal,
    record_lesson_use,
    set_lesson_override,
    update_lesson,
    write_debrief,
)
from tests.fixtures.brain_day import Day, end, monday, place
from tests.fixtures.pnl_desk import MONDAY, TUESDAY, at
from tests.fixtures.strategies import STRADDLE

CALENDAR = MarketCalendar(years=frozenset({2026}), holidays=(), special_sessions=())
NOW = at(TUESDAY, 16, 0)


class Recorder:
    def __init__(self) -> None:
        self.published: list[object] = []

    def publish(self, event: object) -> None:
        self.published.append(event)


@pytest.fixture
def day() -> Iterator[Day]:
    yield monday()


def debrief(day: Day, **changes: object) -> Debrief:
    fields: dict[str, object] = {
        "trading_date": MONDAY,
        "headline": "Killed the straddle early; the hand trade paid",
        "happened": f"Straddle killed at 11:00. See [[strategy:{day.strategy_id}]].",
        "trade_notes": (
            TradeNote(day.run_id, None, "IV was rich", "gave up the afternoon decay"),
            TradeNote(None, day.manual_orders[1], "took the 1% move", "no runner left"),
        ),
        "hindsight": (Hindsight("Size down on event days", True),),
    }
    return Debrief(**{**fields, **changes})  # type: ignore[arg-type]


def test_write_debrief_links_strategies_and_symbols_traded_that_day(day: Day) -> None:
    events = Recorder()

    view = write_debrief(debrief(day), events, NOW, CALENDAR, "mcp:claude-code")

    assert view.note.kind is NoteKind.DAY and view.note.title == "Mon 21 Sep"
    assert {(n.head.kind, n.head.key) for n in view.links_out} == {
        (NoteKind.STRATEGY, day.strategy_id),
        (NoteKind.SYMBOL, "NSE:RELIANCE"),
    }
    [event] = events.published
    assert event == DebriefWritten(
        MONDAY, view.note.note_id, debrief(day).headline, "mcp:claude-code", occurred_at=NOW
    )
    # The words are joined to the record's trades by run and order.
    record = get_day_record(MONDAY, day.desk.sandbox, NOW, CALENDAR)
    run, bought, sold = record.trades
    assert (run.why, run.trade_off) == ("IV was rich", "gave up the afternoon decay")
    assert bought.why is None and sold.why == "took the 1% move"
    assert record.note is not None and record.note.note_id == view.note.note_id


def test_write_debrief_refuses_subject_from_another_day(day: Day) -> None:
    other = debrief(day, trade_notes=(TradeNote(None, day.tuesday_order, "x", "y"),))
    with pytest.raises(BrainNoteError, match="get_day_record lists them"):
        write_debrief(other, Recorder(), NOW, CALENDAR, "ui")
    with pytest.raises(BrainNoteError, match="hasn't happened"):
        write_debrief(debrief(day, trading_date=date(2026, 9, 30)), Recorder(), NOW, CALENDAR, "ui")
    assert brain_repo.find_note(NoteKind.DAY, MONDAY.isoformat()) is None


def test_rewrite_debrief_replaces_agent_part_keeps_user_note(day: Day) -> None:
    first = write_debrief(debrief(day), Recorder(), NOW, CALENDAR, "debrief:2026-09-21")
    edited = edit_user_note(
        first.note.note_id, "My own take", first.note.version, Recorder(), NOW, "ui"
    )

    again = write_debrief(
        debrief(day, headline="Rewritten", trade_notes=(), hindsight=()),
        Recorder(),
        NOW,
        CALENDAR,
        "debrief:2026-09-21",
    )

    assert again.note.note_id == first.note.note_id
    assert again.note.version == edited.note.version + 1
    assert again.note.user_body == "My own take"
    assert again.note.data == {"headline": "Rewritten", "trade_notes": [], "hindsight": []}


def test_edit_user_note_stale_version_conflict_keeps_previous_in_audit(day: Day) -> None:
    bus = build_event_bus({})  # the real one: the audit subscriber records each event
    note = write_debrief(debrief(day), bus, NOW, CALENDAR, "mcp:claude-code").note
    mine = edit_user_note(note.note_id, "First take", note.version, bus, NOW, "ui")

    with pytest.raises(StaleVersionError):
        edit_user_note(note.note_id, "From an old tab", note.version, bus, NOW, "ui")
    edit_user_note(note.note_id, "Second take", mine.note.version, bus, NOW, "ui")
    bus.close()

    [latest, first] = [
        json.loads(e.payload) for e in list_audit(10, event_type=BrainNoteEdited.__name__)
    ]
    assert latest["previous"] == "First take"
    assert first["previous"] is None
    assert brain_repo.get_note(note.note_id).user_body == "Second take"  # type: ignore[union-attr]


def test_unchanged_or_blank_user_note(day: Day) -> None:
    events = Recorder()
    note = write_debrief(debrief(day), events, NOW, CALENDAR, "ui").note
    same = edit_user_note(note.note_id, "  ", note.version, events, NOW, "ui")
    assert same.note.version == note.version  # nothing to change, nothing written
    with pytest.raises(BrainNoteError, match="at most"):
        edit_user_note(note.note_id, "x" * 20_001, note.version, events, NOW, "ui")


def test_every_write_records_who_and_written_by_kind(day: Day) -> None:
    by_job = write_debrief(debrief(day), Recorder(), NOW, CALENDAR, "debrief:2026-09-21")
    assert (by_job.note.written_by, by_job.note.updated_by) == (
        WrittenBy.AGENT_JOB,
        "debrief:2026-09-21",
    )
    by_session = write_debrief(debrief(day), Recorder(), NOW, CALENDAR, "mcp:codex")
    assert (by_session.note.written_by, by_session.note.updated_by) == (
        WrittenBy.PERSON,
        "mcp:codex",
    )
    edited = edit_user_note(
        by_session.note.note_id, "Mine", by_session.note.version, Recorder(), NOW, "ui"
    )
    assert (edited.note.user_updated_by, edited.note.user_updated_at) == ("ui", NOW)
    assert edited.note.updated_by == "mcp:codex"  # the agent's part is still the agent's


MORNING = at(MONDAY, 9, 0)  # before Monday's run and orders ended


def strategy_order(day: Day) -> str:
    with Session(get_engine()) as session:
        order_id = session.scalar(
            select(SandboxTradeRow.order_id).where(SandboxTradeRow.run_id == day.run_id)
        )
    assert order_id
    return order_id


def open_run(strategy_id: str) -> str:
    run = Run(
        id=runs_repo.new_run_id(),
        strategy_id=strategy_id,
        broker="fake",
        product=Product.MIS,
        status=RunStatus.OPEN,
        trigger="schedule",
        started_at=at(TUESDAY, 9, 20),
        legs=(),
    )
    with write_transaction() as session:
        runs_repo.insert_run(session, run)
    return run.id


def desk_lesson(events: Recorder | None = None, now: datetime = MORNING) -> str:
    view = create_lesson(
        "Small edges don't pay their costs",
        "Moves under 1% leave nothing after charges.",
        [],
        [],
        events or Recorder(),
        now,
        "mcp:claude-code",
    )
    return view.note.note_id


def test_create_lesson_links_scope_and_evidence_days(day: Day) -> None:
    events = Recorder()
    view = create_lesson(
        "  Exit the straddle by 11:00  ",
        "Losses cluster after 11:00.",
        [day.strategy_id],
        [f"day:{MONDAY}", f"run:{day.run_id}", f"order:{day.manual_orders[0]}"],
        events,
        NOW,
        "mcp:claude-code",
    )

    assert view.note.title == "Exit the straddle by 11:00"
    assert view.status == "hunch" and view.applies_to == frozenset({day.strategy_id})
    assert {(f.head.kind, f.head.key) for f in view.links_out} == {
        (NoteKind.STRATEGY, day.strategy_id),
        (NoteKind.DAY, MONDAY.isoformat()),
    }
    assert view.lesson is not None
    assert [f"{r.kind.value}:{r.key}" for r in view.lesson.evidence] == [
        f"day:{MONDAY}",
        f"run:{day.run_id}",
        f"order:{day.manual_orders[0]}",
    ]
    [written] = events.published
    assert isinstance(written, LessonWritten) and written.change == "created"
    for applies_to, evidence, refusal in [
        (["nope"], [], "no strategy nope"),
        ([], ["yesterday"], "evidence is day:YYYY-MM-DD"),
        ([], ["run:missing"], "no run missing"),
        ([], ["order:missing"], "no filled order missing"),
    ]:
        with pytest.raises(BrainNoteError, match=refusal):
            create_lesson("t", "b", applies_to, evidence, Recorder(), NOW, "ui")


def test_update_lesson_keeps_what_is_omitted_and_never_its_checks(day: Day) -> None:
    lesson_id = desk_lesson()
    check_lesson(lesson_id, day.run_id, None, CheckOutcome.HELD, "+400", "x", Recorder(), NOW, "ui")
    events = Recorder()

    view = update_lesson(lesson_id, None, "Sharper.", [day.strategy_id], events, NOW, "ui")

    assert view.note.title == "Small edges don't pay their costs"
    assert view.note.body == "Sharper."
    assert view.applies_to == frozenset({day.strategy_id})
    assert view.held is not None and view.held.checks == 1
    assert isinstance(events.published[0], LessonWritten)
    assert update_lesson(lesson_id, None, None, [], Recorder(), NOW, "ui").applies_to == frozenset()
    with pytest.raises(UnknownNoteError, match="no lesson"):
        update_lesson(day.strategy_id, "t", None, None, Recorder(), NOW, "ui")


def test_check_lesson_moves_status_and_publishes_once(day: Day) -> None:
    lesson_id = desk_lesson()
    events = Recorder()
    bought, sold = day.manual_orders

    for run_id, order_id in [(day.run_id, None), (None, bought), (None, sold)]:
        view, check, replaced = check_lesson(
            lesson_id,
            run_id,
            order_id,
            CheckOutcome.HELD,
            "net +120 on a 0.4% move",
            "charges took most of it",
            events,
            NOW,
            "mcp:claude-code",
        )
        assert replaced is None
    assert check.ended_at == at(MONDAY, 14, 0)  # the order's last fill
    view, _, _ = check_lesson(
        lesson_id, None, day.tuesday_order, CheckOutcome.NOT_TESTED, None, "no edge to judge",
        events, NOW, "mcp:claude-code",
    )  # fmt: skip

    assert view.status == "tested"
    assert view.held is not None and (view.held.checks, view.held.held) == (3, 3)
    [moved] = events.published
    assert isinstance(moved, LessonStatusChanged)
    assert (moved.previous, moved.status, moved.held, moved.checks) == ("hunch", "tested", 3, 3)


def test_recheck_same_subject_converges(day: Day) -> None:
    lesson_id = desk_lesson()
    check_lesson(lesson_id, day.run_id, None, CheckOutcome.HELD, "+1", "a", Recorder(), NOW, "ui")

    view, check, replaced = check_lesson(
        lesson_id, day.run_id, None, CheckOutcome.NOT_HELD, "−1", "b", Recorder(), NOW, "ui"
    )

    assert replaced is not None and replaced.outcome is CheckOutcome.HELD
    assert check.outcome is CheckOutcome.NOT_HELD
    assert view.held is not None and (view.held.checks, view.held.held) == (1, 0)
    assert view.lesson is not None and len(view.lesson.checks) == 1


def test_checks_that_dont_count_are_refused(day: Day) -> None:
    desk_wide = desk_lesson()
    scoped = create_lesson(
        "Straddle only", "x", [day.strategy_id], [], Recorder(), MORNING, "ui"
    ).note.note_id
    other = insert_strategy("Other", STRADDLE, MORNING).id
    still_open = open_run(day.strategy_id)
    later = desk_lesson(now=at(MONDAY, 11, 15))

    for lesson_id, run_id, order_id, refusal in [
        (desk_wide, still_open, None, "still open"),
        (later, day.run_id, None, "ended before the lesson was written"),
        (scoped, None, day.manual_orders[0], "doesn't test it"),
        (scoped, open_run(other), None, "still open"),
        (desk_wide, None, strategy_order(day), f"part of run {day.run_id}"),
        (desk_wide, "nope", None, "no run nope"),
        (desk_wide, day.run_id, day.manual_orders[0], "exactly one"),
    ]:
        with pytest.raises(BrainNoteError, match=refusal):
            check_lesson(
                lesson_id, run_id, order_id, CheckOutcome.HELD, "+1", "why", Recorder(), NOW, "ui"
            )
    with pytest.raises(BrainNoteError, match="needs `observed`"):
        check_lesson(
            desk_wide, day.run_id, None, CheckOutcome.HELD, " ", "w", Recorder(), NOW, "ui"
        )


def test_scoped_lesson_refuses_another_strategys_ended_run(day: Day) -> None:
    other = insert_strategy("Other", STRADDLE, MORNING).id
    run_id = open_run(other)
    end(runs_repo.find_run(run_id), at(TUESDAY, 11, 0))  # type: ignore[arg-type]
    scoped = create_lesson(
        "Straddle only", "x", [day.strategy_id], [], Recorder(), MORNING, "ui"
    ).note.note_id

    with pytest.raises(BrainNoteError, match="applies to .* only"):
        check_lesson(scoped, run_id, None, CheckOutcome.HELD, "+1", "w", Recorder(), NOW, "ui")
    check_lesson(scoped, day.run_id, None, CheckOutcome.HELD, "+1", "w", Recorder(), NOW, "ui")


def test_record_lesson_use(day: Day) -> None:
    lesson_id = desk_lesson()

    use = record_lesson_use(
        lesson_id, UsePurpose.DESIGN, day.strategy_id, " sized down ", None, NOW, "mcp:codex"
    )

    assert (use.how, use.used_by, use.used_at) == ("sized down", "mcp:codex", NOW)
    lesson = get_note(lesson_id).lesson
    assert lesson is not None and lesson.used == 1 and lesson.uses == [use]
    with pytest.raises(BrainNoteError, match="no strategy nope"):
        record_lesson_use(lesson_id, UsePurpose.REVIEW, "nope", "x", None, NOW, "ui")
    with pytest.raises(UnknownNoteError):
        record_lesson_use("les_nope", UsePurpose.REVIEW, None, "x", None, NOW, "ui")


def test_retire_and_reinstate_are_a_persons_and_audited(day: Day) -> None:
    lesson_id = desk_lesson()
    events = build_event_bus({})
    try:
        with pytest.raises(BrainNoteError, match="say why"):
            set_lesson_override(lesson_id, Override.RETIRED, " ", events, NOW, "ui")
        with pytest.raises(BrainNoteError, match="isn't retired"):
            set_lesson_override(lesson_id, Override.REINSTATED, None, events, NOW, "ui")

        retired = set_lesson_override(lesson_id, Override.RETIRED, "too vague", events, NOW, "ui")
        assert retired.status == "retired"
        assert (retired.note.override_by, retired.note.override_reason) == ("ui", "too vague")
        assert get_day_record(MONDAY, day.desk.sandbox, NOW, CALENDAR).owed == []
        same = set_lesson_override(lesson_id, Override.RETIRED, "too vague", events, NOW, "ui")
        assert same.note.version == retired.note.version

        back = set_lesson_override(lesson_id, Override.REINSTATED, None, events, NOW, "ui")
        assert back.status == "hunch" and back.lesson is not None and back.lesson.owed
        cleared = set_lesson_override(lesson_id, None, None, events, NOW, "ui")
        assert cleared.note.override is None and cleared.note.override_by is None
    finally:
        events.close()

    audited = [
        (json.loads(e.payload)["previous"], json.loads(e.payload)["status"], e.triggered_by)
        for e in reversed(list_audit(event_type=LessonStatusChanged.__name__, limit=10))
    ]
    assert audited == [
        ("hunch", "retired", "ui"),
        ("retired", "hunch", "ui"),
        ("hunch", "hunch", "ui"),
    ]


def test_reinstated_lesson_waits_before_auto_retiring_again(day: Day) -> None:
    lesson_id = desk_lesson()
    day.desk.now = at(TUESDAY, 11, 0)
    fifth = place(day.desk, Side.SELL, 1, "ui")
    orders = (*day.manual_orders, day.tuesday_order, fifth)
    for run_id, order_id in [(day.run_id, None), *((None, o) for o in orders)]:
        check_lesson(
            lesson_id, run_id, order_id, CheckOutcome.NOT_HELD, "−1", "w", Recorder(), NOW, "ui"
        )
    assert get_note(lesson_id).status == "retired"  # 5 checks, none held: retired by counts

    back = set_lesson_override(lesson_id, Override.REINSTATED, None, Recorder(), NOW, "ui")

    assert back.status == "hunch"  # the counts wait for 5 more checks
    check_lesson(
        lesson_id, day.run_id, None, CheckOutcome.NOT_HELD, "−2", "w", Recorder(),
        at(TUESDAY, 16, 5), "ui",
    )  # fmt: skip
    assert get_note(lesson_id).held == Held(5, 0, 1)
    assert get_note(lesson_id).status == "hunch"


def proposal(day: Day, *based_on: str, change: str = "Exit at 11:00 on expiry") -> Proposal:
    return Proposal(
        day.strategy_id, change, "Losses cluster after 11:00.", "Small sample", based_on
    )


def test_raise_proposal_links_strategy_and_lessons(day: Day) -> None:
    lesson_id = desk_lesson()
    events = Recorder()

    view = raise_proposal(proposal(day, lesson_id), events, NOW, "review:" + day.strategy_id)

    assert (view.note.title, view.status, view.note.strategy_id) == (
        "Exit at 11:00 on expiry",
        "open",
        day.strategy_id,
    )
    assert view.note.written_by is WrittenBy.AGENT_JOB
    assert {f.head.note_id for f in view.links_out} >= {lesson_id}
    assert view.proposal is not None
    assert [f.head.note_id for f in view.proposal.based_on] == [lesson_id]
    assert view.proposal.strategy_name == "Straddle"
    assert view.proposal.request.startswith(f"Change strategy Straddle ({day.strategy_id})")
    [raised] = events.published
    assert isinstance(raised, ProposalRaised) and raised.proposal_id == view.note.note_id
    with pytest.raises(BrainNoteError, match="no lesson les_nope"):
        raise_proposal(proposal(day, "les_nope"), Recorder(), NOW, "ui")
    with pytest.raises(BrainNoteError, match="no lesson"):
        raise_proposal(proposal(day, day.strategy_id), Recorder(), NOW, "ui")  # not a lesson
    with pytest.raises(BrainNoteError, match="no strategy nope"):
        raise_proposal(replace(proposal(day), strategy_id="nope"), Recorder(), NOW, "ui")


def test_decide_proposal_reject_keeps_reason_and_audits(day: Day) -> None:
    rejected = raise_proposal(proposal(day), Recorder(), NOW, "mcp:claude-code").note.note_id
    accepted = raise_proposal(proposal(day, change="Wider stop"), Recorder(), NOW, "mcp:codex")
    events = build_event_bus({})
    try:
        later = decide_proposal(rejected, Decision.LATER, None, events, NOW, "ui")
        assert later.status == "later"
        view = decide_proposal(rejected, Decision.REJECT, " margin too high ", events, NOW, "ui")
        with pytest.raises(BrainNoteError, match="final"):
            decide_proposal(rejected, Decision.ACCEPT, None, events, NOW, "ui")
        decide_proposal(accepted.note.note_id, Decision.ACCEPT, None, events, NOW, "ui")
    finally:
        events.close()

    assert (view.status, view.note.reason) == ("rejected", "margin too high")
    assert (view.note.decided_by, view.note.decided_at) == ("ui", NOW)
    [found] = search_brain(None, NoteKind.PROPOSAL, "rejected", None, 10, NOW)
    assert (found.head.note_id, found.reason) == (rejected, "margin too high")
    assert view.proposal is not None
    assert [(f.head.note_id, f.status) for f in view.proposal.earlier] == [
        (accepted.note.note_id, "open")  # as it was when `view` was read
    ]
    audited = [
        (json.loads(e.payload)["decision"], json.loads(e.payload)["reason"], e.triggered_by)
        for e in reversed(list_audit(event_type=ProposalDecided.__name__, limit=10))
    ]
    assert audited == [
        ("later", None, "ui"),
        ("reject", "margin too high", "ui"),
        ("accept", None, "ui"),
    ]
    with pytest.raises(UnknownNoteError, match="no proposal"):
        decide_proposal(day.strategy_id, Decision.ACCEPT, None, Recorder(), NOW, "ui")
