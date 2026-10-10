from datetime import UTC, date, datetime

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from openticker.core.brain import lessons
from openticker.core.brain.lessons import CheckOutcome
from openticker.core.brain.notes import BrainNoteError, Debrief, NoteKind, TradeNote, WrittenBy
from openticker.core.calendar.models import MarketCalendar
from openticker.core.pnl import DayPnl
from openticker.ports.models import Side
from openticker.storage.sqlite import brain_repo, pnl_repo
from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.models import BrainLessonCheckRow, BrainNoteRow, SandboxTradeRow
from openticker.storage.sqlite.strategies_repo import insert_strategy, update_strategy
from openticker.use_cases.brain.read import (
    UnknownNoteError,
    get_day_record,
    get_graph,
    get_note,
    search_brain,
)
from openticker.use_cases.brain.write import check_lesson, create_lesson, write_debrief
from openticker.use_cases.reset_paper_account import reset_paper_account
from tests.fixtures.brain_day import Day, monday
from tests.fixtures.pnl_desk import MONDAY, TUESDAY, at, new_desk
from tests.fixtures.strategies import SIGNAL_EVERYTHING, STRADDLE

NOW = datetime(2026, 10, 5, 10, 0, tzinfo=UTC)  # a Monday


class Recorder:
    def publish(self, event: object) -> None:
        pass


CALENDAR = MarketCalendar(years=frozenset({2026}), holidays=(), special_sessions=())


def lesson(title: str, body: str = "", strategy_id: str | None = None) -> str:
    with Session(get_engine()) as session:
        note = brain_repo.write_note(
            session,
            None,
            NoteKind.LESSON,
            "",
            title=title,
            body=body,
            data={},
            state=None,
            strategy_id=None,
            structural=((NoteKind.STRATEGY, strategy_id),) if strategy_id else (),
            written_by=WrittenBy.AGENT_JOB,
            now=NOW,
            by="debrief:2026-10-05",
        )
        session.commit()
        return note.note_id


def check(lesson_id: str, n: int, outcome: CheckOutcome) -> None:
    with Session(get_engine()) as session:
        session.add(
            BrainLessonCheckRow(
                lesson_id=lesson_id,
                subject=f"run:run_{n}",
                run_id=f"run_{n}",
                outcome=outcome,
                observed="exit 10:55",
                why="",
                checked_by="debrief:2026-10-05",
                checked_at=NOW.replace(tzinfo=None),
            )
        )
        session.commit()


def test_graph_has_every_strategy_and_the_symbols_it_trades() -> None:
    straddle = insert_strategy("Straddle", STRADDLE, NOW)
    signals = insert_strategy("Everything", SIGNAL_EVERYTHING, NOW)

    view = get_graph("30", NOW, CALENDAR)

    titles = {n.note_id: n.title for n in view.notes}
    assert sorted(titles.values()) == [
        "Everything",
        "NIFTY 50",
        "NIFTY29SEP26FUT",
        "RELIANCE",
        "Straddle",
    ]
    pairs = {(titles[link.from_id], titles[link.to_id]) for link in view.links}
    assert pairs == {
        ("Straddle", "NIFTY 50"),
        ("Everything", "RELIANCE"),
        ("Everything", "NIFTY29SEP26FUT"),
    }
    update_strategy(straddle.id, "Short straddle", STRADDLE, NOW)
    assert "Short straddle" in {n.title for n in get_graph("30", NOW, CALENDAR).notes}
    assert signals.id in {n.key for n in view.notes}


def test_graph_days_carry_their_net_after_charges() -> None:
    lesson("Gaps", "Seen [[day:2026-10-01]] and [[day:2026-10-02]].")
    pnl_repo.upsert_day(DayPnl(date(2026, 10, 1), 1800.0, 195.0, 0.0, 1605.0, 0.0, 4, True), NOW)

    view = get_graph("7", NOW, CALENDAR)

    net = {n.key: view.day_net.get(n.note_id) for n in view.notes if n.kind is NoteKind.DAY}
    assert net == {"2026-10-01": 1605.0, "2026-10-02": None}


def test_graph_window_counts_trading_days() -> None:
    lesson("Then", "[[day:2026-09-25]] [[day:2026-09-24]]")  # a Friday and a Thursday
    # The last 7 trading days to Monday 5 Oct start Friday 25 Sep.
    keys = {n.key for n in get_graph("7", NOW, CALENDAR).notes if n.kind is NoteKind.DAY}
    assert keys == {"2026-09-25"}


def test_lesson_status_derived_follows_threshold_change(monkeypatch: pytest.MonkeyPatch) -> None:
    lesson_id = lesson("Exit by 11:00 on expiry")
    for n, outcome in enumerate([CheckOutcome.HELD, CheckOutcome.HELD, CheckOutcome.NOT_HELD]):
        check(lesson_id, n, outcome)

    assert get_note(lesson_id).status == "tested"
    monkeypatch.setattr(lessons, "TESTED_AT", (3, 0.7))
    view = get_note(lesson_id)
    assert view.status == "hunch"
    assert view.next_step == "Tested after 1 more check that holds."
    assert get_graph("30", NOW, CALENDAR).status[lesson_id] == "hunch"


def test_search_filters_on_derived_status() -> None:
    tested = lesson("Tested one")
    lesson("Hunch one")
    for n in range(3):
        check(tested, n, CheckOutcome.HELD)

    found = search_brain(None, NoteKind.LESSON, "tested", None, 20, NOW)

    assert [f.head.note_id for f in found] == [tested]
    assert found[0].held is not None and found[0].held.checks == 3


def test_backlinks() -> None:
    first = lesson("First")
    second = lesson("Second", f"Builds on [[lesson:{first}|the first]]; see [[run:run_7]].")

    view = get_note(first)
    assert [f.head.note_id for f in view.backlinks] == [second]
    assert view.links_out == []
    cited = get_note(second)
    assert [(r.kind.value, r.key) for r in cited.facts] == [("run", "run_7")]
    assert [f.status for f in cited.links_out] == ["hunch"]


def test_local_links_include_links_between_neighbours() -> None:
    first = lesson("First", "Seen on [[day:2026-10-01]].")
    second = lesson("Second", f"Builds on [[lesson:{first}]], also [[day:2026-10-01]].")
    lesson("Elsewhere", f"Only [[lesson:{second}]].")  # a neighbour of second, not of first

    view = get_note(first)
    ids = {f.head.key: f.head.note_id for f in [*view.links_out, *view.backlinks]}
    pairs = {(link.from_id, link.to_id) for link in view.local_links}

    day = ids["2026-10-01"]
    # its own links, and the one between its neighbours: second → the day
    assert pairs == {(first, day), (second, first), (second, day)}
    assert len(view.local_links) == len(pairs)


def test_lesson_scope_comes_from_its_links() -> None:
    strategy = insert_strategy("Straddle", STRADDLE, NOW)
    scoped = lesson("Scoped", strategy_id=strategy.id)
    desk = lesson("Desk-wide")

    assert get_note(scoped).applies_to == frozenset({strategy.id})
    assert get_note(desk).applies_to == frozenset()
    about = search_brain(None, NoteKind.LESSON, None, strategy.id, 20, NOW)
    assert [f.head.note_id for f in about] == [scoped]


def test_unknown_note_says_where_to_find_one() -> None:
    with pytest.raises(UnknownNoteError, match="search_brain"):
        get_note("les_nope")


# The day record (Monday 21 Sep: a strategy run and a round trip by hand).

TUESDAY_CLOSE = at(TUESDAY, 15, 0)


def test_day_record_groups_by_run_then_order_with_placed_by() -> None:
    day = monday()

    record = get_day_record(MONDAY, day.desk.sandbox, TUESDAY_CLOSE, CALENDAR)

    run, bought, sold = record.trades
    assert (run.run_id, run.strategy_name, run.triggered_by) == (
        day.run_id,
        "Straddle",
        f"strategy:{day.strategy_id}",
    )
    assert [f.side for f in run.fills] == [Side.SELL, Side.BUY]
    assert (run.run_status, run.stop_reason) == ("ended", "kill")
    assert (bought.order_id, bought.triggered_by) == (day.manual_orders[0], "ui")
    assert (sold.order_id, sold.triggered_by) == (day.manual_orders[1], "mcp:claude-code")
    assert day.tuesday_order not in {t.order_id for t in record.trades}  # Tuesday's isn't Monday's


def test_day_record_numbers_come_from_the_record() -> None:
    day = monday()

    record = get_day_record(MONDAY, day.desk.sandbox, TUESDAY_CLOSE, CALENDAR)
    run = record.trades[0]
    fills = [f for t in record.trades for f in t.fills]
    assert run.realized_pnl == 100.0  # sold 10 at 1,000, bought back at 990
    assert run.charges == round(sum(f.charges or 0.0 for f in run.fills), 2) > 0
    assert run.net == round(100.0 - run.charges, 2)
    # Not recorded after the close: the fills alone, and no net without the marks.
    assert not record.live and record.figures.net_pnl is None
    assert record.figures.fills == len(fills) == 4
    assert record.figures.charges == round(sum(f.charges or 0.0 for f in fills), 2)

    # A charge corrected in the trade book is the record's new figure.
    with Session(get_engine()) as session:
        session.execute(
            update(SandboxTradeRow)
            .where(SandboxTradeRow.order_id == run.fills[0].order_id)
            .values(charges=50.0)
        )
        session.commit()
    again = get_day_record(MONDAY, day.desk.sandbox, TUESDAY_CLOSE, CALENDAR)
    assert again.trades[0].charges == round(50.0 + (run.fills[1].charges or 0.0), 2)


def test_day_record_for_past_date_reads_that_date() -> None:
    day = monday()
    pnl_repo.upsert_day(DayPnl(MONDAY, 120.0, 30.0, 0.0, 90.0, 0.0, 4, True), TUESDAY_CLOSE)

    monday_record = get_day_record(MONDAY, day.desk.sandbox, TUESDAY_CLOSE, CALENDAR)
    tuesday_record = get_day_record(TUESDAY, day.desk.sandbox, TUESDAY_CLOSE, CALENDAR)

    assert monday_record.figures.net_pnl == 90.0 and not monday_record.live
    assert [t.order_id for t in tuesday_record.trades] == [day.tuesday_order]
    assert tuesday_record.live  # today, worked out from the broker's marks
    assert tuesday_record.figures.net_pnl is not None


def test_day_record_refuses_future_and_closed_days() -> None:
    desk = new_desk()
    with pytest.raises(BrainNoteError, match="hasn't happened"):
        get_day_record(date(2026, 9, 23), desk.sandbox, TUESDAY_CLOSE, CALENDAR)
    with pytest.raises(BrainNoteError, match="wasn't a trading day"):
        get_day_record(date(2026, 9, 20), desk.sandbox, TUESDAY_CLOSE, CALENDAR)


def test_owed_checks_listed_until_answered() -> None:
    day = monday()
    with Session(get_engine()) as session:
        early = brain_repo.write_note(
            session,
            None,
            NoteKind.LESSON,
            "",
            title="Desk-wide",
            body="",
            data={},
            state=None,
            strategy_id=None,
            structural=(),
            written_by=WrittenBy.PERSON,
            now=at(MONDAY, 9, 0),
            by="ui",
        )
        session.commit()
    retired = lesson("Retired by a person")  # written "now" (5 Oct): after Monday, owes nothing
    record = get_day_record(MONDAY, day.desk.sandbox, TUESDAY_CLOSE, CALENDAR)
    assert {(o.lesson_id, o.run_id or o.order_id) for o in record.owed} == {
        (early.note_id, day.run_id),
        (early.note_id, day.manual_orders[0]),
        (early.note_id, day.manual_orders[1]),
    }
    assert retired not in {o.lesson_id for o in record.owed}

    with Session(get_engine()) as session:
        row = session.get(BrainNoteRow, early.note_id)
        assert row is not None
        session.add(
            BrainLessonCheckRow(
                lesson_id=early.note_id,
                subject=f"run:{day.run_id}",
                run_id=day.run_id,
                outcome=CheckOutcome.HELD,
                observed="out by 11:00",
                why="",
                checked_by="ui",
                checked_at=TUESDAY_CLOSE.replace(tzinfo=None),
            )
        )
        session.commit()
    owed = get_day_record(MONDAY, day.desk.sandbox, TUESDAY_CLOSE, CALENDAR).owed
    assert {o.run_id or o.order_id for o in owed} == set(day.manual_orders)

    with Session(get_engine()) as session:
        row = session.get(BrainNoteRow, early.note_id)
        assert row is not None
        row.override = lessons.Override.RETIRED
        session.commit()
    assert get_day_record(MONDAY, day.desk.sandbox, TUESDAY_CLOSE, CALENDAR).owed == []


def debriefed_monday() -> tuple[Day, str]:
    day = monday()
    view = write_debrief(
        Debrief(
            MONDAY,
            "Straddle killed; the hand trade paid",
            "x",
            (TradeNote(None, day.manual_orders[1], "took the move", "no runner"),),
            (),
        ),
        Recorder(),
        TUESDAY_CLOSE,
        CALENDAR,
        "ui",
    )
    return day, view.note.note_id


def test_day_record_lists_the_checks_given_on_its_trades() -> None:
    day, _ = debriefed_monday()
    lesson_id = create_lesson("L", "b", [], [], Recorder(), at(MONDAY, 9, 0), "ui").note.note_id
    check_lesson(
        lesson_id, None, day.manual_orders[0], CheckOutcome.HELD, "+50", "w", Recorder(),
        TUESDAY_CLOSE, "ui",
    )  # fmt: skip

    record = get_day_record(MONDAY, day.desk.sandbox, TUESDAY_CLOSE, CALENDAR)

    [(given, title)] = record.checks
    assert (given.order_id, title) == (day.manual_orders[0], "L")
    assert {o.run_id or o.order_id for o in record.owed} == {day.run_id, day.manual_orders[1]}


def test_reset_freezes_debriefed_days_and_day_record_reads_frozen() -> None:
    day, note_id = debriefed_monday()
    pnl_repo.upsert_day(DayPnl(MONDAY, 120.0, 30.0, 0.0, 90.0, 0.0, 4, True), TUESDAY_CLOSE)
    before = get_day_record(MONDAY, day.desk.sandbox, TUESDAY_CLOSE, CALENDAR)
    reset_at = at(TUESDAY, 15, 30)

    reset_paper_account("RESET", 1_000_000.0, Recorder(), reset_at, "ui")

    after = get_day_record(MONDAY, day.desk.sandbox, reset_at, CALENDAR)
    assert after.frozen_at == reset_at
    assert after.figures == before.figures
    assert [(t.subject, t.charges, t.net, t.why) for t in after.trades] == [
        (t.subject, t.charges, t.net, t.why) for t in before.trades
    ]
    assert get_graph("all", reset_at, CALENDAR).day_net[note_id] == 90.0  # daily_pnl is gone
    # Tuesday wasn't debriefed: nothing kept, its trades are gone.
    assert get_day_record(TUESDAY, day.desk.sandbox, reset_at, CALENDAR).trades == []
    # Written again after the reset, the debrief still reads the frozen record.
    write_debrief(
        Debrief(MONDAY, "Again", "y", (TradeNote(day.run_id, None, "w", "t"),), ()),
        Recorder(),
        reset_at,
        CALENDAR,
        "ui",
    )
    again = get_day_record(MONDAY, day.desk.sandbox, reset_at, CALENDAR)
    assert again.frozen_at == reset_at and again.trades[0].why == "w"


def test_checks_marked_before_reset_still_count() -> None:
    day, _ = debriefed_monday()
    lesson_id = create_lesson("L", "b", [], [], Recorder(), at(MONDAY, 9, 0), "ui").note.note_id
    for order_id in day.manual_orders:
        check_lesson(
            lesson_id, None, order_id, CheckOutcome.HELD, "+1", "w", Recorder(), TUESDAY_CLOSE,
            "ui",
        )  # fmt: skip

    reset_paper_account("RESET", 1_000_000.0, Recorder(), at(TUESDAY, 15, 30), "ui")

    view = get_note(lesson_id)
    assert view.held is not None and (view.held.checks, view.held.held) == (2, 2)
    assert view.lesson is not None
    assert {c.reset_at for c in view.lesson.checks} == {at(TUESDAY, 15, 30)}
    assert [o.run_id for o in view.lesson.owed] == [day.run_id]  # runs are kept; orders aren't
