from datetime import UTC, datetime, timedelta

from openticker.core.brain.learning import (
    Design,
    LearningCounts,
    LessonAt,
    Review,
    Use,
    count_learning,
    learning,
)
from openticker.core.brain.lessons import CheckOutcome, UsePurpose

T0 = datetime(2026, 10, 5, 4, 0, tzinfo=UTC)


def lesson(written: datetime, *strategies: str, live: bool = True) -> LessonAt:
    return LessonAt(f"les_{len(strategies)}{written:%H%M}", written, frozenset(strategies), live)


def use(
    purpose: UsePurpose, at: datetime, by: str = "mcp:claude-code", strategy: str | None = None
) -> Use:
    return Use(purpose, strategy, by, at)


def counts(**kwargs: object) -> LearningCounts:
    args: dict[str, object] = {
        "lessons": [],
        "designs": [],
        "reviews": [],
        "uses": [],
        "checks": [],
        "checks_owed": 0,
        "lessons_ruled": 0,
        **kwargs,
    }
    return count_learning(**args)  # type: ignore[arg-type]


def test_learning_counts_only_designs_and_reviews_with_lessons() -> None:
    later = T0 + timedelta(hours=1)
    result = counts(
        lessons=[lesson(T0), lesson(T0, "stg_a")],
        designs=[
            Design("stg_before", T0 - timedelta(hours=1), "mcp:claude-code"),  # no lesson yet
            Design("stg_new", later, "mcp:claude-code"),  # a desk lesson was live, no use
        ],
        reviews=[
            Review("stg_a", later, later + timedelta(minutes=5)),  # its own lesson applied
            Review("stg_b", T0 - timedelta(hours=2), T0 - timedelta(hours=1)),  # none yet
        ],
    )

    assert (result.designs, result.designs_citing) == (1, 0)
    assert (result.reviews, result.reviews_citing) == (1, 0)


def test_design_cites_only_with_same_clients_use_near_its_creation() -> None:
    made = T0 + timedelta(hours=1)
    design = Design("stg_new", made, "mcp:claude-code")
    lessons = [lesson(T0)]

    def cited(*uses: Use) -> int:
        return counts(lessons=lessons, designs=[design], uses=list(uses)).designs_citing

    assert cited(use(UsePurpose.DESIGN, made - timedelta(minutes=10))) == 1
    assert cited(use(UsePurpose.DESIGN, made + timedelta(minutes=10))) == 1
    assert cited(use(UsePurpose.DESIGN, made - timedelta(minutes=31))) == 0
    assert cited(use(UsePurpose.DESIGN, made, by="mcp:codex")) == 0
    assert cited(use(UsePurpose.ANSWER, made)) == 0


def test_design_by_unknown_creator_takes_anyones_use() -> None:
    made = T0 + timedelta(hours=1)
    result = counts(
        lessons=[lesson(T0)],
        designs=[Design("stg_old", made, None)],
        uses=[use(UsePurpose.DESIGN, made, by="mcp:codex")],
    )

    assert result.designs_citing == 1


def test_a_citing_design_counts_even_without_a_desk_lesson() -> None:
    made = T0 + timedelta(hours=1)
    result = counts(
        lessons=[lesson(T0, "stg_a")],  # only about another strategy
        designs=[Design("stg_new", made, "mcp:claude-code")],
        uses=[use(UsePurpose.DESIGN, made)],
    )

    assert (result.designs, result.designs_citing) == (1, 1)


def test_review_cites_with_its_strategys_use_while_it_ran() -> None:
    start, end = T0 + timedelta(hours=1), T0 + timedelta(hours=1, minutes=8)
    review = Review("stg_a", start, end)

    def cited(*uses: Use) -> tuple[int, int]:
        result = counts(lessons=[lesson(T0, "stg_a")], reviews=[review], uses=list(uses))
        return result.reviews, result.reviews_citing

    inside = start + timedelta(minutes=4)
    assert cited(use(UsePurpose.REVIEW, inside, "review:stg_a", "stg_a")) == (1, 1)
    assert cited(use(UsePurpose.REVIEW, inside, "review:stg_b", "stg_b")) == (1, 0)
    assert cited(use(UsePurpose.REVIEW, end + timedelta(minutes=1), "review:stg_a", "stg_a")) == (
        1,
        0,
    )


def test_retired_and_other_strategies_lessons_dont_apply_to_a_review() -> None:
    later = T0 + timedelta(hours=1)
    result = counts(
        lessons=[lesson(T0, "stg_b"), lesson(T0, live=False)],
        reviews=[Review("stg_a", later, later + timedelta(minutes=5))],
    )

    assert result.reviews == 0


def test_lessons_held_more_often_than_not() -> None:
    result = counts(
        checks=[
            ("les_a", CheckOutcome.HELD),
            ("les_a", CheckOutcome.HELD),
            ("les_a", CheckOutcome.NOT_HELD),
            ("les_b", CheckOutcome.HELD),
            ("les_b", CheckOutcome.NOT_HELD),  # a tie isn't held
            ("les_c", CheckOutcome.NOT_TESTED),  # not checked
        ],
        checks_owed=4,
        lessons_ruled=1,
    )

    assert (result.lessons_checked, result.lessons_held) == (2, 1)
    assert (result.checks_answered, result.checks_owed, result.lessons_ruled) == (6, 4, 1)


def test_shares_are_none_when_nothing_could_count() -> None:
    empty = learning(counts())
    some = learning(
        LearningCounts(
            designs=3,
            designs_citing=2,
            reviews=1,
            reviews_citing=1,
            checks_answered=0,
            checks_owed=0,
            lessons_checked=4,
            lessons_held=1,
            lessons_ruled=0,
        )
    )

    assert (empty.cite_share, empty.held_share) == (None, None)
    assert (some.cite_share, some.held_share) == (0.75, 0.25)
