from datetime import UTC, datetime, timedelta

import pytest

from openticker.core.brain.lessons import (
    NO_CHECKS,
    CheckOutcome,
    Held,
    LessonStatus,
    Override,
    Subject,
    lesson_status,
    next_step,
    parse_evidence,
    validate_check,
    validate_lesson,
    why_not_counted,
)
from openticker.core.brain.notes import BrainNoteError


def test_new_lesson_is_a_hunch() -> None:
    assert lesson_status(NO_CHECKS, None) is LessonStatus.HUNCH


def test_hunch_to_tested_at_three_checks_sixty_percent() -> None:
    assert lesson_status(Held(2, 2, 0), None) is LessonStatus.HUNCH
    assert lesson_status(Held(3, 2, 0), None) is LessonStatus.TESTED
    assert lesson_status(Held(5, 3, 0), None) is LessonStatus.TESTED  # exactly 60%


def test_stays_hunch_below_sixty_percent() -> None:
    assert lesson_status(Held(4, 2, 0), None) is LessonStatus.HUNCH


def test_tested_to_rule_at_ten_checks_seventy_percent() -> None:
    assert lesson_status(Held(9, 9, 0), None) is LessonStatus.TESTED
    assert lesson_status(Held(10, 7, 0), None) is LessonStatus.RULE


def test_rule_falls_back_to_tested_when_share_drops() -> None:
    assert lesson_status(Held(12, 8, 0), None) is LessonStatus.TESTED  # 67%


def test_auto_retired_at_five_checks_below_forty_percent() -> None:
    assert lesson_status(Held(4, 0, 0), None) is LessonStatus.HUNCH
    assert lesson_status(Held(5, 1, 0), None) is LessonStatus.RETIRED
    assert lesson_status(Held(5, 2, 0), None) is LessonStatus.HUNCH  # exactly 40% stays


def test_person_retire_beats_any_count() -> None:
    assert lesson_status(Held(20, 20, 0), Override.RETIRED) is LessonStatus.RETIRED


def test_reinstated_not_auto_retired_until_five_more_checks() -> None:
    assert lesson_status(Held(9, 2, 4), Override.REINSTATED) is LessonStatus.HUNCH
    assert lesson_status(Held(10, 2, 5), Override.REINSTATED) is LessonStatus.RETIRED


@pytest.mark.parametrize(
    ("held", "status", "step"),
    [
        (NO_CHECKS, LessonStatus.HUNCH, "Tested after 3 more checks that hold."),
        (Held(4, 2, 0), LessonStatus.HUNCH, "Tested after 1 more check that holds."),
        (Held(9, 7, 0), LessonStatus.TESTED, "Rule after 1 more check that holds."),
        (Held(10, 7, 0), LessonStatus.RULE, "A rule while 70% or more of its checks hold."),
    ],
)
def test_next_step_says_how_many_more_checks(held: Held, status: LessonStatus, step: str) -> None:
    assert next_step(held, status) == step


WRITTEN = datetime(2026, 9, 21, 3, 30, tzinfo=UTC)
LATER = WRITTEN + timedelta(hours=2)


def run(strategy_id: str = "s1", ended_at: datetime | None = LATER) -> Subject:
    return Subject("run_1", None, strategy_id, ended_at)


ORDER = Subject(None, "ord_1", None, LATER)


def test_open_run_and_run_before_lesson_do_not_count() -> None:
    assert why_not_counted(run(ended_at=None), WRITTEN, frozenset()) == (
        "run run_1 is still open: check it once it has ended"
    )
    refused = why_not_counted(run(ended_at=WRITTEN), WRITTEN, frozenset())
    assert refused is not None and "ended before the lesson was written" in refused


def test_scoped_lesson_refuses_other_strategy_and_orders() -> None:
    scope = frozenset({"s1"})
    assert why_not_counted(run("s1"), WRITTEN, scope) is None
    assert "applies to s1 only" in (why_not_counted(run("s2"), WRITTEN, scope) or "")
    assert "doesn't test it" in (why_not_counted(ORDER, WRITTEN, scope) or "")


def test_desk_wide_takes_runs_and_orders() -> None:
    assert why_not_counted(run("any"), WRITTEN, frozenset()) is None
    assert why_not_counted(ORDER, WRITTEN, frozenset()) is None


def test_held_needs_observed_figure() -> None:
    with pytest.raises(BrainNoteError, match="needs `observed`"):
        validate_check(CheckOutcome.HELD, "  ", "it held")
    with pytest.raises(BrainNoteError, match="needs `observed`"):
        validate_check(CheckOutcome.NOT_HELD, None, "it didn't")
    with pytest.raises(BrainNoteError, match="needs its why"):
        validate_check(CheckOutcome.NOT_TESTED, None, " ")
    assert validate_check(CheckOutcome.NOT_TESTED, " ", " no expiry ") == (None, "no expiry")
    assert validate_check(CheckOutcome.HELD, " +840 ", "w") == ("+840", "w")


def test_lesson_needs_title_and_text_within_limits() -> None:
    assert validate_lesson("  t ", " b ") == ("t", "b")
    with pytest.raises(BrainNoteError, match="needs a title"):
        validate_lesson(" ", "b")
    with pytest.raises(BrainNoteError, match="needs its text"):
        validate_lesson("t", "")
    with pytest.raises(BrainNoteError, match="at most 120"):
        validate_lesson("t" * 121, "b")


def test_evidence_is_days_runs_and_orders_once_each() -> None:
    refs = parse_evidence(["day:2026-09-21", "run:r1", "order:o1", "run:r1"])
    assert [(r.kind.value, r.key) for r in refs] == [
        ("day", "2026-09-21"),
        ("run", "r1"),
        ("order", "o1"),
    ]
    for bad in ["2026-09-21", "day:21 Sep", "run:", "lesson:les_1"]:
        with pytest.raises(BrainNoteError):
            parse_evidence([bad])
    with pytest.raises(BrainNoteError, match="at most 50"):
        parse_evidence([f"run:r{n}" for n in range(51)])
