from collections.abc import Iterator
from datetime import timedelta

import pytest

from openticker.core.agents.jobs import AgentJobEndReason, AgentJobKind, Harness
from openticker.core.brain.lessons import CheckOutcome, Override, UsePurpose
from openticker.core.brain.notes import BrainNoteError
from openticker.storage.sqlite import agent_jobs_repo
from openticker.storage.sqlite.strategies_repo import insert_strategy, write_transaction
from openticker.use_cases.brain.read import get_learning
from openticker.use_cases.brain.write import (
    check_lesson,
    create_lesson,
    record_lesson_use,
    set_lesson_override,
)
from tests.fixtures.brain_day import Day, monday
from tests.fixtures.pnl_desk import MONDAY, TUESDAY, at
from tests.fixtures.strategies import STRADDLE

NOW = at(TUESDAY, 16, 0)


class Recorder:
    def publish(self, event: object) -> None:
        pass


@pytest.fixture
def day() -> Iterator[Day]:
    yield monday()


def lesson(*strategies: str) -> str:
    view = create_lesson(
        "Exit before 11:00",
        "Losses cluster after 11:00.",
        list(strategies),
        [],
        Recorder(),
        at(MONDAY, 9, 0),
        "mcp:claude-code",
    )
    return view.note.note_id


def review(strategy_id: str, minutes_ago: int) -> None:
    start = NOW - timedelta(minutes=minutes_ago)
    with write_transaction() as session:
        job = agent_jobs_repo.add_job(
            session, AgentJobKind.REVIEW, strategy_id, Harness.CLAUDE, "ui", start
        )
        agent_jobs_repo.mark_running(session, job.id, 4242, start)
        agent_jobs_repo.end_job(
            session,
            job.id,
            AgentJobEndReason.FINISHED,
            "exited with code 0",
            start + timedelta(minutes=5),
        )


def test_get_learning_counts_designs_reviews_checks_from_the_record(day: Day) -> None:
    desk = lesson()
    about = lesson(day.strategy_id)
    insert_strategy("Strangle", STRADDLE, NOW - timedelta(minutes=50), "mcp:claude-code")
    insert_strategy("Iron fly", STRADDLE, NOW - timedelta(minutes=40), "mcp:codex")
    record_lesson_use(
        desk,
        UsePurpose.DESIGN,
        None,
        "sized down",
        None,
        NOW - timedelta(minutes=55),
        "mcp:claude-code",
    )
    review(day.strategy_id, minutes_ago=30)
    record_lesson_use(
        about,
        UsePurpose.REVIEW,
        day.strategy_id,
        "kept the exit",
        None,
        NOW - timedelta(minutes=28),
        f"review:{day.strategy_id}",
    )
    review(day.strategy_id, minutes_ago=10)  # read no lesson
    check_lesson(
        about,
        day.run_id,
        None,
        CheckOutcome.HELD,
        "flat by 10:55",
        "exited early",
        Recorder(),
        NOW,
        "ui",
    )

    view = get_learning(30, NOW)
    counts = view.learning.counts

    assert view.since == NOW - timedelta(days=30)
    # Monday's Straddle was created after the desk lesson too, citing none
    assert (counts.designs, counts.designs_citing) == (3, 1)
    assert (counts.reviews, counts.reviews_citing) == (2, 1)
    assert view.learning.cite_share == 0.4
    assert (counts.checks_answered, counts.lessons_checked, counts.lessons_held) == (1, 1, 1)
    # the desk lesson still owes checks on Monday's and Tuesday's orders
    assert counts.checks_owed == 4
    assert counts.lessons_ruled == 0


def test_get_learning_leaves_out_retired_lessons_and_old_records(day: Day) -> None:
    retired = lesson()
    set_lesson_override(retired, Override.RETIRED, "wrong", Recorder(), NOW, "ui")
    insert_strategy("Strangle", STRADDLE, NOW - timedelta(minutes=50), "mcp:claude-code")

    view = get_learning(30, NOW)

    assert (view.learning.counts.designs, view.learning.counts.checks_owed) == (0, 0)
    assert view.learning.cite_share is None
    assert get_learning(1, NOW + timedelta(days=3)).learning.counts.designs == 0


def test_get_learning_days_bounded() -> None:
    with pytest.raises(BrainNoteError):
        get_learning(0, NOW)
