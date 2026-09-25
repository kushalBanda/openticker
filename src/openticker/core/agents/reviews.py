"""When a strategy's review is due on the user's schedule (ADR 29 in
docs/adr). Pure.

A schedule has up to three triggers: every so many minutes, hours or days;
after so many runs; and when the strategy's drawdown reaches an amount. Each
counts from the later of the last review and the moment the schedule was
set. A review is due only when a run has ended after costs since then:
the reviewer judges ended runs, so without a new one it would read what it
read last time, and be paid for it.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from openticker.core.strategies.ledger import LedgerRun

MIN_EVERY = timedelta(minutes=5)
MAX_EVERY = timedelta(days=90)
MAX_AFTER_RUNS = 1_000

_EVERY = re.compile(r"^\s*(\d+)\s*([mhd])\s*$")
_UNITS = {"m": timedelta(minutes=1), "h": timedelta(hours=1), "d": timedelta(days=1)}


class ReviewScheduleError(ValueError):
    pass


@dataclass(frozen=True)
class ReviewSchedule:
    set_at: datetime  # tz-aware UTC; the triggers count from here until the first review
    every: timedelta | None = None
    after_runs: int | None = None  # runs after costs since the last review
    drawdown: float | None = None  # rupees of net P&L below its high

    def __post_init__(self) -> None:
        if self.every is None and self.after_runs is None and self.drawdown is None:
            raise ReviewScheduleError(
                "a review schedule needs at least one of every, after_runs or drawdown"
            )
        if self.every is not None and not MIN_EVERY <= self.every <= MAX_EVERY:
            raise ReviewScheduleError(
                f"every must be from {every_text(MIN_EVERY)} to {every_text(MAX_EVERY)}, "
                f"got {every_text(self.every)}"
            )
        if self.after_runs is not None and not 1 <= self.after_runs <= MAX_AFTER_RUNS:
            raise ReviewScheduleError(
                f"after_runs must be from 1 to {MAX_AFTER_RUNS}, got {self.after_runs}"
            )
        if self.drawdown is not None and self.drawdown <= 0:
            raise ReviewScheduleError(
                f"drawdown is a loss in rupees and must be above 0, got {self.drawdown}"
            )


def parse_every(text: str) -> timedelta:
    """ "90m", "4h" or "2d"."""
    match = _EVERY.match(text.lower())
    if match is None:
        raise ReviewScheduleError(
            f"every is a number and a unit, m (minutes), h (hours) or d (days), like 30m, "
            f"4h or 1d; got {text!r}"
        )
    return int(match[1]) * _UNITS[match[2]]


def every_text(every: timedelta) -> str:
    minutes = int(every.total_seconds() // 60)
    if minutes % (24 * 60) == 0:
        return f"{minutes // (24 * 60)}d"
    if minutes % 60 == 0:
        return f"{minutes // 60}h"
    return f"{minutes}m"


def review_due(
    schedule: ReviewSchedule,
    runs: Sequence[LedgerRun],
    last_review_at: datetime | None,
    now: datetime,
) -> str | None:
    """Why a review is due now, or None. `runs` are the strategy's, any order;
    `last_review_at` is when its last review was asked for, by anyone."""
    since = max(schedule.set_at, last_review_at) if last_review_at else schedule.set_at
    judged = sorted((r for r in runs if r.after_costs), key=lambda r: r.run.started_at)
    new = [r for r in judged if r.run.ended_at is not None and r.run.ended_at > since]
    if not new:
        return None
    if schedule.every is not None and now - since >= schedule.every:
        return f"every {every_text(schedule.every)}"
    if schedule.after_runs is not None and len(new) >= schedule.after_runs:
        return f"{len(new)} runs after costs since the last review"
    if schedule.drawdown is not None:
        reached = _drawdown_reached(judged, {r.run.id for r in new}, schedule.drawdown)
        if reached is not None:
            return f"drawdown {reached:,.2f}, past {schedule.drawdown:,.2f}"
    return None


def _drawdown_reached(runs: Sequence[LedgerRun], new: set[str], amount: float) -> float | None:
    """The drawdown now, when a new run took it to `amount` or past it from
    above it. Cumulative net P&L is counted from 0, in start order; a
    drawdown that was already that deep at the last review is not news."""
    cumulative = high = drawdown = 0.0
    crossed = False
    for run in runs:
        before = drawdown
        cumulative += run.net_pnl
        high = max(high, cumulative)
        drawdown = round(high - cumulative, 2)
        crossed = crossed or (run.run.id in new and before < amount <= drawdown)
    return drawdown if crossed else None
