from dataclasses import replace
from datetime import UTC, datetime, time

import pytest

from openticker.core.agents.debriefs import (
    DayActivity,
    DebriefOutcome,
    DebriefSchedule,
    DebriefScheduleError,
    debrief_due,
    parse_at,
)

AT = DebriefSchedule(time(15, 45))
AFTER = datetime(2026, 10, 5, 10, 20, tzinfo=UTC)  # 15:50 IST
BEFORE = datetime(2026, 10, 5, 10, 10, tzinfo=UTC)  # 15:40 IST
BUSY = DayActivity(
    pnl_recorded=True, fills=4, runs_ended=0, kills=0, checks_owed=0, debrief_exists=False
)
QUIET = replace(BUSY, fills=0)


def test_nothing_when_off() -> None:
    assert debrief_due(None, AFTER, True, BUSY) is DebriefOutcome.NOTHING


def test_nothing_on_holiday() -> None:
    assert debrief_due(AT, AFTER, False, BUSY) is DebriefOutcome.NOTHING


def test_wait_before_time() -> None:
    assert debrief_due(AT, BEFORE, True, BUSY) is DebriefOutcome.WAIT


def test_wait_until_pnl_recorded() -> None:
    assert debrief_due(AT, AFTER, True, replace(BUSY, pnl_recorded=False)) is DebriefOutcome.WAIT


def test_nothing_when_already_written() -> None:
    assert debrief_due(AT, AFTER, True, replace(BUSY, debrief_exists=True)) is (
        DebriefOutcome.NOTHING
    )
    assert debrief_due(AT, AFTER, True, replace(QUIET, debrief_exists=True)) is (
        DebriefOutcome.NOTHING
    )


def test_quiet_when_no_activity() -> None:
    assert debrief_due(AT, AFTER, True, QUIET) is DebriefOutcome.QUIET


@pytest.mark.parametrize(
    "busy",
    [
        replace(QUIET, fills=1),
        replace(QUIET, runs_ended=1),
        replace(QUIET, kills=1),
        replace(QUIET, checks_owed=1),
    ],
)
def test_due_with_fills_runs_kills_or_owed_checks(busy: DayActivity) -> None:
    assert debrief_due(AT, AFTER, True, busy) is DebriefOutcome.DUE


def test_schedule_refuses_before_1540() -> None:
    assert parse_at("15:40") == DebriefSchedule(time(15, 40))
    with pytest.raises(DebriefScheduleError, match="15:40 or later"):
        parse_at("15:39")
    with pytest.raises(DebriefScheduleError, match="HH:MM"):
        parse_at("4pm")
