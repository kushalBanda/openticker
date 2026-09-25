from datetime import UTC, datetime, timedelta

import pytest

from openticker.core.agents.reviews import (
    ReviewSchedule,
    ReviewScheduleError,
    every_text,
    parse_every,
    review_due,
)
from openticker.core.strategies.ledger import LedgerFill, LedgerRun
from openticker.core.strategies.runs import LegStatus, Run, RunLeg, RunStatus
from openticker.ports.models import Exchange, Product, Side

SET = datetime(2026, 9, 1, 4, 0, tzinfo=UTC)
SYMBOL = "NIFTY29SEP2625000CE"


def _run(day: int, net: float, charged: bool = True, ended: bool = True) -> LedgerRun:
    """A run started on day `day` after SET and ended six hours later, netting
    `net` after 10 of charges."""
    gross = net + 10
    leg = RunLeg(
        "ce",
        SYMBOL,
        Exchange.NFO,
        Side.SELL,
        10,
        LegStatus.CLOSED,
        entry_price=100.0,
        exit_price=100.0 - gross / 10,
    )
    started = SET + timedelta(days=day)
    run = Run(
        id=f"run{day}",
        strategy_id="stg",
        broker="fake",
        product=Product.NRML,
        status=RunStatus.ENDED if ended else RunStatus.OPEN,
        trigger="schedule",
        started_at=started,
        legs=(leg,),
        ended_at=started + timedelta(hours=6) if ended else None,
    )
    charges = 5.0 if charged else None
    fills = (
        LedgerFill(SYMBOL, "NFO", Side.SELL, 10, 100.0, started, 100.0, charges),
        LedgerFill(SYMBOL, "NFO", Side.BUY, 10, 100.0 - gross / 10, started, None, charges),
    )
    return LedgerRun(run, fills)


def _at(day: int, hours: int = 0) -> datetime:
    return SET + timedelta(days=day, hours=hours)


def test_every_reads_minutes_hours_and_days_and_says_them_back() -> None:
    assert parse_every("30m") == timedelta(minutes=30)
    assert parse_every(" 4H ") == timedelta(hours=4)
    assert parse_every("2d") == timedelta(days=2)
    assert [every_text(parse_every(t)) for t in ("90m", "120m", "1440m")] == ["90m", "2h", "1d"]
    with pytest.raises(ReviewScheduleError, match="like 30m, 4h or 1d"):
        parse_every("weekly")


def test_a_schedule_needs_a_trigger_within_bounds() -> None:
    with pytest.raises(ReviewScheduleError, match="at least one"):
        ReviewSchedule(SET)
    with pytest.raises(ReviewScheduleError, match="from 5m to 90d"):
        ReviewSchedule(SET, every=timedelta(minutes=1))
    with pytest.raises(ReviewScheduleError, match="after_runs"):
        ReviewSchedule(SET, after_runs=0)
    with pytest.raises(ReviewScheduleError, match="above 0"):
        ReviewSchedule(SET, drawdown=-500)


def test_nothing_is_due_without_a_run_ended_after_costs_since_the_last_review() -> None:
    schedule = ReviewSchedule(SET, every=timedelta(hours=1), after_runs=1, drawdown=1)
    open_run = _run(1, -900, ended=False)
    uncharged = _run(2, -900, charged=False)

    assert review_due(schedule, [], None, _at(30)) is None
    assert review_due(schedule, [open_run, uncharged], None, _at(30)) is None
    # A run that ended before the last review was already read.
    assert review_due(schedule, [_run(1, -900)], _at(2), _at(30)) is None


def test_every_counts_from_the_last_review_or_from_when_it_was_set() -> None:
    schedule = ReviewSchedule(SET, every=timedelta(days=1))
    runs = [_run(0, 100)]  # ended six hours after SET

    assert review_due(schedule, runs, None, _at(0, 23)) is None
    assert review_due(schedule, runs, None, _at(1)) == "every 1d"
    runs.append(_run(3, 100))
    assert review_due(schedule, runs, _at(3), _at(3, 23)) is None
    assert review_due(schedule, runs, _at(3), _at(4)) == "every 1d"


def test_after_runs_counts_runs_ended_since_the_last_review() -> None:
    schedule = ReviewSchedule(SET, after_runs=3)
    runs = [_run(day, 100) for day in range(5)]  # ending on days 0 to 4

    assert review_due(schedule, runs[:2], None, _at(9)) is None
    assert (
        review_due(schedule, runs[:3], None, _at(9)) == "3 runs after costs since the last review"
    )
    assert review_due(schedule, runs, _at(2, 7), _at(9)) is None  # only days 3 and 4 since


def test_a_schedule_set_later_starts_counting_then() -> None:
    runs = [_run(day, 100) for day in range(5)]  # ending on days 0 to 4

    assert review_due(ReviewSchedule(_at(2), after_runs=4), runs, _at(-5), _at(9)) is None
    assert review_due(ReviewSchedule(_at(2), after_runs=3), runs, _at(-5), _at(9)) is not None


def test_a_drawdown_is_due_once_when_it_reaches_the_amount() -> None:
    schedule = ReviewSchedule(SET, drawdown=1_000)
    runs = [_run(0, 500), _run(1, -600)]  # 600 below the high

    assert review_due(schedule, runs, None, _at(9)) is None
    runs.append(_run(2, -500))  # 1,100 below
    assert review_due(schedule, runs, None, _at(9)) == "drawdown 1,100.00, past 1,000.00"
    runs.append(_run(3, -100))  # deeper, but it was reviewed on the way in
    assert review_due(schedule, runs, _at(2, 7), _at(9)) is None
    runs.extend([_run(4, 3_000), _run(5, -1_200)])  # a new high, then a new fall
    assert review_due(schedule, runs, _at(3, 7), _at(9)) == "drawdown 1,200.00, past 1,000.00"


def test_a_drawdown_says_how_deep_it_is_now_not_where_it_crossed() -> None:
    schedule = ReviewSchedule(SET, drawdown=1_000)
    runs = [_run(0, 500), _run(1, -1_100), _run(2, -900)]  # crosses on day 1, deeper on day 2

    assert review_due(schedule, runs, None, _at(9)) == "drawdown 2,000.00, past 1,000.00"
