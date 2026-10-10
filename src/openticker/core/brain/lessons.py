"""A lesson's status, derived from its checks every time it is read, so it
follows the thresholds below whatever they were when the checks were given.
Only a person's override is stored.

           checks ≥3, held ≥60%           checks ≥10, held ≥70%
  HUNCH ───────────────────────▶ TESTED ───────────────────────▶ RULE
    ▲  ◀─── share drops below ───  │  ◀──── share drops below ────  │
    │                              │                               │
    └──────────┬───────────────────┴───────────────┬───────────────┘
               │ checks ≥5 and held <40% (auto)    │ person: retire
               ▼                                   ▼
            RETIRED ◀──────────────────────────────┘
               │ person: reinstate → counts decide again; auto-retire waits
               ▼   for 5 more checks after the reinstatement
           (by counts)

A not_tested answer never counts toward checks.

A check is about one ended run, or one order placed outside a strategy, and
counts only when that ended after the lesson was written and is in its
scope: a lesson with no strategies applies to the whole desk (runs and
orders alike), one with strategies only to their runs. Checking the same
run or order again replaces the earlier answer.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from openticker.core.brain.notes import (
    MAX_BODY,
    MAX_LINE,
    MAX_TITLE,
    BrainNoteError,
    FactKind,
    NoteKind,
    Ref,
    note_key,
)


class LessonStatus(StrEnum):
    HUNCH = "hunch"
    TESTED = "tested"
    RULE = "rule"
    RETIRED = "retired"


class Override(StrEnum):
    RETIRED = "retired"
    REINSTATED = "reinstated"


class CheckOutcome(StrEnum):
    HELD = "held"
    NOT_HELD = "not_held"
    NOT_TESTED = "not_tested"


class UsePurpose(StrEnum):
    """What a lesson was relied on for."""

    DESIGN = "design"
    REVIEW = "review"
    DEBRIEF = "debrief"
    ANSWER = "answer"


MAX_APPLIES_TO = 20
MAX_EVIDENCE = 50


TESTED_AT = (3, 0.60)
RULE_AT = (10, 0.70)
AUTO_RETIRE_AT = (5, 0.40)
AUTO_RETIRE_GRACE = 5  # checks after a reinstatement before auto-retire applies again


@dataclass(frozen=True)
class Held:
    checks: int  # held + not_held
    held: int
    since_override: int  # checks after the latest reinstatement

    @property
    def share(self) -> float | None:
        """None with no checks."""
        return self.held / self.checks if self.checks else None


NO_CHECKS = Held(0, 0, 0)


def _reaches(held: Held, at: tuple[int, float]) -> bool:
    checks, share = at
    return held.checks >= checks and held.held / held.checks >= share - 1e-9


def lesson_status(held: Held, override: Override | None) -> LessonStatus:
    if override is Override.RETIRED:
        return LessonStatus.RETIRED
    grace = override is Override.REINSTATED and held.since_override < AUTO_RETIRE_GRACE
    checks, below = AUTO_RETIRE_AT
    if not grace and held.checks >= checks and held.held / held.checks < below - 1e-9:
        return LessonStatus.RETIRED
    if _reaches(held, RULE_AT):
        return LessonStatus.RULE
    if _reaches(held, TESTED_AT):
        return LessonStatus.TESTED
    return LessonStatus.HUNCH


def next_step(held: Held, status: LessonStatus) -> str:
    """What would move it next, in words: "Rule after 1 more check that holds"."""
    if status is LessonStatus.RETIRED:
        return "Retired: agents don't rely on it. A person can reinstate it."
    if status is LessonStatus.RULE:
        return f"A rule while {RULE_AT[1]:.0%} or more of its checks hold."
    goal, target = ("Tested", TESTED_AT) if status is LessonStatus.HUNCH else ("Rule", RULE_AT)
    more = 0
    while not _reaches(Held(held.checks + more, held.held + more, 0), target):
        more += 1
    plural = "check that holds" if more == 1 else "checks that hold"
    return f"{goal} after {more} more {plural}."


@dataclass(frozen=True)
class Subject:
    """What a check is about: one run, or one order placed outside a strategy."""

    run_id: str | None
    order_id: str | None  # exactly one of the two
    strategy_id: str | None  # None for an order outside a strategy
    ended_at: datetime | None  # the run's end, or the order's last fill; None: still open

    @property
    def key(self) -> str:
        return f"run:{self.run_id}" if self.run_id else f"order:{self.order_id}"

    def __str__(self) -> str:
        return f"run {self.run_id}" if self.run_id else f"order {self.order_id}"


def why_not_counted(
    subject: Subject, lesson_created_at: datetime, scope: frozenset[str]
) -> str | None:
    """None when a check on `subject` counts toward the lesson; otherwise why not."""
    if subject.ended_at is None:
        return f"{subject} is still open: check it once it has ended"
    if subject.ended_at <= lesson_created_at:
        return (
            f"{subject} ended before the lesson was written: it can be the lesson's "
            "evidence, not a check of it"
        )
    if scope and subject.order_id:
        return (
            f"the lesson applies to strategies {', '.join(sorted(scope))}; an order placed "
            "outside a strategy doesn't test it"
        )
    if scope and subject.strategy_id not in scope:
        return (
            f"{subject} is strategy {subject.strategy_id}'s; the lesson applies to "
            f"{', '.join(sorted(scope))} only"
        )
    return None


def validate_check(outcome: CheckOutcome, observed: str | None, why: str) -> tuple[str | None, str]:
    """The observed figure and the why, trimmed. Held and not held need what
    was observed: the figure the judgement rests on."""
    why = why.strip()
    observed = (observed or "").strip() or None
    if not why:
        raise BrainNoteError("a check needs its why: one line on how the run bore it out or not")
    if observed is None and outcome is not CheckOutcome.NOT_TESTED:
        raise BrainNoteError(
            f"a {outcome.value} check needs `observed`: the figure it rests on, e.g. "
            '"P&L at 11:00 +840, at exit −1,260". Answer not_tested when the run didn\'t test it'
        )
    _within(why, MAX_LINE, "the why")
    if observed is not None:
        _within(observed, MAX_LINE, "observed")
    return observed, why


def validate_lesson(title: str, body: str) -> tuple[str, str]:
    """A lesson's title and text, trimmed."""
    title, body = title.strip(), body.strip()
    if not title:
        raise BrainNoteError("a lesson needs a title: the lesson in one line")
    if not body:
        raise BrainNoteError("a lesson needs its text: what was seen, and what to do about it")
    _within(title, MAX_TITLE, "the title")
    _within(body, MAX_BODY, "the lesson's text")
    return title, body


def parse_evidence(items: Sequence[str]) -> tuple[Ref, ...]:
    """What a lesson came from: days (day:YYYY-MM-DD), runs (run:<id>) and
    orders (order:<id>), each once, in order."""
    if len(items) > MAX_EVIDENCE:
        raise BrainNoteError(f"at most {MAX_EVIDENCE} pieces of evidence")
    refs: list[Ref] = []
    for item in items:
        kind, _, key = item.strip().partition(":")
        if kind == NoteKind.DAY:
            refs.append(Ref(NoteKind.DAY, note_key(NoteKind.DAY, key), None))
        elif kind in (FactKind.RUN, FactKind.ORDER) and key.strip():
            refs.append(Ref(FactKind(kind), key.strip(), None))
        else:
            raise BrainNoteError(
                f"evidence is day:YYYY-MM-DD, run:<id> or order:<id>, not {item!r}"
            )
    return tuple(dict.fromkeys(refs))


def _within(text: str, most: int, what: str) -> None:
    if len(text) > most:
        raise BrainNoteError(f"{what} is {len(text):,} characters; at most {most:,}")
