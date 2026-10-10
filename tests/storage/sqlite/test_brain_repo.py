from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from openticker.core.brain.lessons import CheckOutcome, Held, Override
from openticker.core.brain.notes import NoteKind, WrittenBy
from openticker.storage.sqlite import brain_repo
from openticker.storage.sqlite.brain_repo import (
    DeskStrategy,
    LessonCheck,
    Note,
    StaleVersionError,
)
from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.models import BrainLessonCheckRow, BrainNoteRow
from openticker.storage.sqlite.strategies_repo import insert_strategy
from openticker.use_cases.pnl_history import day_window
from tests.fixtures.brain_day import monday
from tests.fixtures.pnl_desk import MONDAY, at
from tests.fixtures.strategies import STRADDLE

NOW = datetime(2026, 10, 5, 10, 0, tzinfo=UTC)


def write(
    kind: NoteKind,
    body: str = "",
    *,
    key: str = "",
    title: str = "A note",
    structural: tuple[tuple[NoteKind, str], ...] = (),
    note_id: str | None = None,
    now: datetime = NOW,
    data: dict[str, object] | None = None,
) -> Note:
    with Session(get_engine()) as session:
        note = brain_repo.write_note(
            session,
            note_id,
            kind,
            key,
            title=title,
            body=body,
            data=data or {},
            state=None,
            strategy_id=None,
            structural=structural,
            written_by=WrittenBy.PERSON,
            now=now,
            by="mcp:claude-code",
        )
        session.commit()
        return note


def linked(note_id: str) -> tuple[list[str], list[str]]:
    out, back = brain_repo.links_of(note_id)
    return [n.key for n in out], [n.key for n in back]


def test_body_links_rederived_on_rewrite() -> None:
    first = write(NoteKind.LESSON, "Seen on [[day:2026-10-05]] in [[symbol:nse:reliance]].")
    assert linked(first.note_id)[0] == ["2026-10-05", "NSE:RELIANCE"]

    again = write(NoteKind.LESSON, "Only [[day:2026-10-01|Thursday]].", note_id=first.note_id)

    assert again.version == 2
    assert linked(first.note_id)[0] == ["2026-10-01"]
    day = brain_repo.find_note(NoteKind.DAY, "2026-10-01")
    assert day is not None and day.title == "Thu 1 Oct"
    assert linked(day.note_id)[1] == [first.note_id]


def test_links_to_unknown_notes_stay_text() -> None:
    note = write(NoteKind.LESSON, "[[lesson:les_nope]] [[strategy:str_nope]] [[run:run_1]]")
    assert linked(note.note_id) == ([], [])


def test_structural_links_create_target_notes() -> None:
    strategy = insert_strategy("Straddle", STRADDLE, NOW)

    lesson = write(NoteKind.LESSON, structural=((NoteKind.STRATEGY, strategy.id),))

    note = brain_repo.find_note(NoteKind.STRATEGY, strategy.id)
    assert note is not None and note.title == "Straddle" and note.written_by is WrittenBy.SERVER
    assert linked(lesson.note_id)[0] == [strategy.id]


def test_lesson_scope_is_its_links() -> None:
    strategy = insert_strategy("Straddle", STRADDLE, NOW)
    scoped = write(NoteKind.LESSON, structural=((NoteKind.STRATEGY, strategy.id),))
    # A wikilink to a strategy is a mention, not a scope.
    desk = write(NoteKind.LESSON, f"Unlike [[strategy:{strategy.id}]].")

    with Session(get_engine()) as session:
        scopes = brain_repo.scope_of(session, [scoped.note_id, desk.note_id])

    assert scopes == {scoped.note_id: frozenset({strategy.id}), desk.note_id: frozenset()}


def test_held_counts_one_query_for_many_lessons() -> None:
    lessons = [write(NoteKind.LESSON, title=f"Lesson {n}") for n in range(3)]
    reinstated_at = NOW + timedelta(hours=1)
    with Session(get_engine()) as session:
        row = session.get(BrainNoteRow, lessons[1].note_id)
        assert row is not None
        row.override = Override.REINSTATED
        row.override_at = reinstated_at.replace(tzinfo=None)
        outcomes = [
            (lessons[0], CheckOutcome.HELD, NOW),
            (lessons[0], CheckOutcome.NOT_HELD, NOW),
            (lessons[0], CheckOutcome.NOT_TESTED, NOW),
            (lessons[1], CheckOutcome.HELD, NOW),
            (lessons[1], CheckOutcome.HELD, reinstated_at + timedelta(minutes=1)),
        ]
        for n, (lesson, outcome, at) in enumerate(outcomes):
            session.add(
                BrainLessonCheckRow(
                    lesson_id=lesson.note_id,
                    subject=f"run:run_{n}",
                    run_id=f"run_{n}",
                    outcome=outcome,
                    observed="x",
                    why="y",
                    checked_by="mcp",
                    checked_at=at.replace(tzinfo=None),
                )
            )
        session.commit()

        queries: list[str] = []
        engine = session.get_bind()
        event.listen(engine, "before_cursor_execute", lambda *a: queries.append(a[2]))
        held = brain_repo.held_counts(session, [lesson.note_id for lesson in lessons])

    assert len(queries) == 1
    assert held == {lessons[0].note_id: Held(2, 1, 0), lessons[1].note_id: Held(2, 2, 1)}


def test_graph_window_and_truncation_flag() -> None:
    old = NOW - timedelta(days=60)
    write(NoteKind.DAY, key="2026-08-03", title="Mon 3 Aug", now=old)
    write(NoteKind.DAY, key="2026-10-05", title="Mon 5 Oct")
    stale = write(NoteKind.LESSON, title="Old lesson", now=old)
    fresh = write(NoteKind.LESSON, f"Unlike [[lesson:{stale.note_id}]]", title="New lesson")
    brain_repo.sync_strategies([DeskStrategy("str_1", "Gone", ())], old)

    notes, links, truncated = brain_repo.graph(date(2026, 9, 1), 10)

    assert {n.title for n in notes} == {"Mon 5 Oct", "New lesson", "Gone"}
    assert links == [] and not truncated  # the stale lesson is out, so is its link
    everything, links, _ = brain_repo.graph(None, 10)
    assert len(everything) == 5 and [(lk.from_id, lk.to_id) for lk in links] == [
        (fresh.note_id, stale.note_id)
    ]
    newest, _, truncated = brain_repo.graph(None, 2)
    assert [n.title for n in newest] == ["Mon 5 Oct", "New lesson"] and truncated


def test_search_by_text_kind_strategy() -> None:
    strategy = insert_strategy("Straddle", STRADDLE, NOW)
    scoped = write(
        NoteKind.LESSON,
        "Exit by 11:00 on expiry, 100% of the time",
        title="Expiry exits",
        structural=((NoteKind.STRATEGY, strategy.id),),
    )
    write(NoteKind.LESSON, "Gaps under 0.4% don't pay", title="Gaps")

    assert [n.note_id for n in brain_repo.search("expiry", None, None, 10)] == [scoped.note_id]
    assert len(brain_repo.search("%", NoteKind.LESSON, None, 10)) == 2  # % is text
    assert len(brain_repo.search("0_4", None, None, 10)) == 0  # _ is text
    about = brain_repo.search(None, None, strategy.id, 10)
    assert {n.kind for n in about} == {NoteKind.LESSON, NoteKind.STRATEGY}
    assert [n.title for n in brain_repo.search(None, NoteKind.LESSON, strategy.id, 10)] == [
        "Expiry exits"
    ]


def test_sync_strategies_writes_only_on_change_and_follows_renames() -> None:
    desk = [DeskStrategy("str_1", "ORB", ("NSE:RELIANCE", "NSE:HDFCBANK"))]
    brain_repo.sync_strategies(desk, NOW)
    note = brain_repo.find_note(NoteKind.STRATEGY, "str_1")
    assert note is not None
    assert linked(note.note_id)[0] == ["NSE:HDFCBANK", "NSE:RELIANCE"]

    brain_repo.sync_strategies(desk, NOW + timedelta(days=1))
    same = brain_repo.find_note(NoteKind.STRATEGY, "str_1")
    assert same is not None and same.updated_at == NOW

    brain_repo.sync_strategies([DeskStrategy("str_1", "ORB 2", ("NSE:RELIANCE",))], NOW)
    renamed = brain_repo.find_note(NoteKind.STRATEGY, "str_1")
    assert renamed is not None and renamed.title == "ORB 2"
    assert linked(note.note_id)[0] == ["NSE:RELIANCE"]


def test_reads_at_once_make_each_strategy_note_once() -> None:
    from concurrent.futures import ThreadPoolExecutor

    desk = [DeskStrategy(f"str_{n}", f"S{n}", ("NSE:SBIN",)) for n in range(5)]
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda _: brain_repo.sync_strategies(desk, NOW), range(8)))

    assert len(brain_repo.search(None, NoteKind.STRATEGY, None, None)) == 5
    assert len(brain_repo.search(None, NoteKind.SYMBOL, None, None)) == 1


def test_user_body_survives_agent_rewrite() -> None:
    note = write(NoteKind.LESSON, "First")
    with Session(get_engine()) as session:
        written = brain_repo.write_user_body(
            session, note.note_id, "Mine [[day:2026-10-02]]", note.version, NOW, "ui"
        )
        session.commit()
    assert written is not None and written[1] is None

    again = write(NoteKind.LESSON, "Second", note_id=note.note_id)

    assert again.user_body == "Mine [[day:2026-10-02]]" and again.version == note.version + 2
    assert linked(note.note_id)[0] == ["2026-10-02"]  # the user's links count too


def test_stale_version_refused() -> None:
    note = write(NoteKind.LESSON, "First")
    write(NoteKind.LESSON, "Second", note_id=note.note_id)  # an agent wrote meanwhile

    with Session(get_engine()) as session, pytest.raises(StaleVersionError):
        brain_repo.write_user_body(session, note.note_id, "Mine", note.version, NOW, "ui")
    with Session(get_engine()) as session:
        assert brain_repo.write_user_body(session, "bn_none", "Mine", 1, NOW, "ui") is None
    stored = brain_repo.get_note(note.note_id)
    assert stored is not None and stored.user_body is None


def test_owed_checks_set_based_runs_and_orders_minus_answered() -> None:
    day = monday()
    other = insert_strategy("Other", STRADDLE, NOW)
    written = at(MONDAY, 9, 0)
    desk_wide = write(NoteKind.LESSON, title="Desk", now=written)
    scoped = write(
        NoteKind.LESSON,
        title="Straddle only",
        structural=((NoteKind.STRATEGY, day.strategy_id),),
        now=written,
    )
    elsewhere = write(
        NoteKind.LESSON,
        title="Other only",
        structural=((NoteKind.STRATEGY, other.id),),
        now=written,
    )
    late = write(NoteKind.LESSON, title="Written after", now=at(MONDAY, 12, 0))
    with Session(get_engine()) as session:
        session.add(
            BrainLessonCheckRow(
                lesson_id=desk_wide.note_id,
                subject=f"order:{day.manual_orders[0]}",
                order_id=day.manual_orders[0],
                outcome=CheckOutcome.NOT_TESTED,
                observed=None,
                why="no setup",
                checked_by="ui",
                checked_at=NOW.replace(tzinfo=None),
            )
        )
        session.commit()

        queries: list[str] = []
        event.listen(session.get_bind(), "before_cursor_execute", lambda *a: queries.append(a[2]))
        start, end = day_window(MONDAY)
        owed = brain_repo.owed_checks(session, start, end)

    assert len(queries) == 1
    assert [o.run_id or o.order_id for o in owed] == [day.run_id] * 2 + [day.manual_orders[1]] * 2
    assert {(o.lesson_title, o.run_id or o.order_id) for o in owed} == {
        ("Desk", day.run_id),
        ("Straddle only", day.run_id),
        ("Desk", day.manual_orders[1]),  # the buy was answered, not-tested or not
        ("Written after", day.manual_orders[1]),  # written at noon, before the 14:00 sell
    }
    assert elsewhere.note_id not in {o.lesson_id for o in owed}
    assert scoped.note_id not in {o.lesson_id for o in owed if o.order_id}
    assert late.note_id not in {o.lesson_id for o in owed if o.run_id}


def test_check_upsert_replaces_and_returns_previous() -> None:
    lesson = write(NoteKind.LESSON, title="L")
    first = LessonCheck(
        lesson_id=lesson.note_id,
        run_id=None,
        order_id="ord_1",
        strategy_id=None,
        ended_at=NOW,
        outcome=CheckOutcome.HELD,
        observed="+10",
        why="a",
        checked_by="ui",
        checked_at=NOW,
    )
    second = replace(first, outcome=CheckOutcome.NOT_HELD, observed="−10", checked_by="mcp:codex")
    with Session(get_engine()) as session:
        assert brain_repo.upsert_check(session, first) is None
        brain_repo.mark_checks_before_reset(session, NOW)
        assert brain_repo.upsert_check(session, second) == replace(first, reset_at=NOW)
        session.commit()
        assert brain_repo.checks_of(session, lesson.note_id, 10) == [second]
        assert brain_repo.held_counts(session, [lesson.note_id]) == {lesson.note_id: Held(1, 0, 0)}


def test_freeze_days_keeps_the_record_and_rewrites_keep_it() -> None:
    day = write(NoteKind.DAY, key="2026-09-21", data={"headline": "h"})
    with Session(get_engine()) as session:
        assert brain_repo.unfrozen_debriefs(session) == ["2026-09-21"]
        assert brain_repo.freeze_days(session, {"2026-09-21": {"figures": 1}}, NOW) == 1
        assert brain_repo.unfrozen_debriefs(session) == []
        brain_repo.write_note(
            session,
            day.note_id,
            NoteKind.DAY,
            "2026-09-21",
            title="t",
            body="again",
            data={"headline": "h2"},
            state=None,
            strategy_id=None,
            structural=(),
            written_by=WrittenBy.PERSON,
            now=NOW,
            by="ui",
            keep=("frozen", "frozen_at"),
        )
        session.commit()
    note = brain_repo.get_note(day.note_id)
    assert note is not None
    assert note.data == {"headline": "h2", "frozen": {"figures": 1}, "frozen_at": NOW.isoformat()}
