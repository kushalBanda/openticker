"""Whether the brain is being read: of the strategies designed and the
reviews finished in a window, while a lesson applied, how many recorded
relying on one; how many checks are still owed; how often lessons held.

  design ── created while a desk-wide lesson was live ─┐
  review ── finished while a lesson about its strategy  ├─▶ could cite
            or the desk was live                        │
                                                        ▼
  cited ◀── a use recorded for it: a design's by the same client within
            CITE_WINDOW of the strategy's creation; a review's for its
            strategy while the job ran

A design or review that recorded a use counts as one that could cite, even
when no lesson was live by these rules: it read one. Counted from the
record alone, never from what an agent says it did.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from openticker.core.brain.lessons import CheckOutcome, UsePurpose

CITE_WINDOW = timedelta(minutes=30)  # either side of a strategy's creation


@dataclass(frozen=True)
class LessonAt:
    lesson_id: str
    written_at: datetime
    strategies: frozenset[str]  # its scope; empty: the whole desk
    live: bool  # not retired now


@dataclass(frozen=True)
class Design:
    strategy_id: str
    created_at: datetime
    created_by: str | None  # None for a strategy created before this was recorded


@dataclass(frozen=True)
class Review:
    strategy_id: str
    started_at: datetime
    ended_at: datetime


@dataclass(frozen=True)
class Use:
    purpose: UsePurpose
    strategy_id: str | None
    used_by: str
    used_at: datetime


@dataclass(frozen=True)
class LearningCounts:
    designs: int  # strategies created while a lesson applied
    designs_citing: int  # of those, with a lesson's use recorded for it
    reviews: int  # review jobs finished while a lesson applied
    reviews_citing: int
    checks_answered: int  # given in the window, not_tested included
    checks_owed: int  # runs and orders in the window a live lesson still waits on
    lessons_checked: int  # lessons held or not held at least once in the window
    lessons_held: int  # of those, held more often than not
    lessons_ruled: int  # rules now


@dataclass(frozen=True)
class Learning:
    counts: LearningCounts
    cite_share: float | None  # None: nothing could have cited
    held_share: float | None  # None: no lesson was checked


def learning(counts: LearningCounts) -> Learning:
    could = counts.designs + counts.reviews
    cited = counts.designs_citing + counts.reviews_citing
    return Learning(
        counts,
        cited / could if could else None,
        counts.lessons_held / counts.lessons_checked if counts.lessons_checked else None,
    )


def design_cited(design: Design, uses: Iterable[Use]) -> bool:
    return any(
        u.purpose is UsePurpose.DESIGN
        and abs(u.used_at - design.created_at) <= CITE_WINDOW
        and (design.created_by is None or u.used_by == design.created_by)
        for u in uses
    )


def review_cited(review: Review, uses: Iterable[Use]) -> bool:
    return any(
        u.purpose is UsePurpose.REVIEW
        and u.strategy_id == review.strategy_id
        and review.started_at <= u.used_at <= review.ended_at
        for u in uses
    )


def count_learning(
    lessons: Sequence[LessonAt],
    designs: Sequence[Design],
    reviews: Sequence[Review],
    uses: Sequence[Use],
    checks: Sequence[tuple[str, CheckOutcome]],
    checks_owed: int,
    lessons_ruled: int,
) -> LearningCounts:
    """`checks` are (lesson id, outcome) for the checks given in the window."""

    def desk_lesson_before(at: datetime) -> bool:
        return any(
            lesson.live and not lesson.strategies and lesson.written_at < at for lesson in lessons
        )

    def lesson_about_before(strategy_id: str, at: datetime) -> bool:
        return any(
            lesson.live
            and (not lesson.strategies or strategy_id in lesson.strategies)
            and lesson.written_at < at
            for lesson in lessons
        )

    designs_could = designs_cited = 0
    for design in designs:
        cited = design_cited(design, uses)
        if cited or desk_lesson_before(design.created_at):
            designs_could += 1
            designs_cited += cited
    reviews_could = reviews_cited = 0
    for review in reviews:
        cited = review_cited(review, uses)
        if cited or lesson_about_before(review.strategy_id, review.started_at):
            reviews_could += 1
            reviews_cited += cited

    held: dict[str, int] = {}
    not_held: dict[str, int] = {}
    for lesson_id, outcome in checks:
        if outcome is CheckOutcome.HELD:
            held[lesson_id] = held.get(lesson_id, 0) + 1
        elif outcome is CheckOutcome.NOT_HELD:
            not_held[lesson_id] = not_held.get(lesson_id, 0) + 1
    checked = held.keys() | not_held.keys()
    return LearningCounts(
        designs=designs_could,
        designs_citing=designs_cited,
        reviews=reviews_could,
        reviews_citing=reviews_cited,
        checks_answered=len(checks),
        checks_owed=checks_owed,
        lessons_checked=len(checked),
        lessons_held=sum(held.get(i, 0) > not_held.get(i, 0) for i in checked),
        lessons_ruled=lessons_ruled,
    )
