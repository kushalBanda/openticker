from datetime import UTC, date, datetime, time

import pytest

from openticker.core.calendar.models import Holiday, MarketCalendar, SpecialSession
from openticker.core.scripts.models import (
    InvalidScriptError,
    ScriptLimits,
    ScriptSchedule,
    ScriptStopReason,
    exit_reason,
)
from openticker.core.scripts.schedule import in_window, stop_due
from openticker.ports.models import EXCHANGE_TIMEZONE, Exchange
from tests.fixtures.calendar import NO_HOLIDAYS

SCHEDULE = ScriptSchedule(start_time=time(9, 15), stop_time=time(15, 0))


def _ist(day: int, hour: int, minute: int) -> datetime:
    """September 2026, exchange time; the 22nd is a Tuesday."""
    return datetime(2026, 9, day, hour, minute, tzinfo=EXCHANGE_TIMEZONE).astimezone(UTC)


def test_the_window_runs_from_start_time_to_stop_time() -> None:
    assert not in_window(SCHEDULE, NO_HOLIDAYS, _ist(22, 9, 14))
    assert in_window(SCHEDULE, NO_HOLIDAYS, _ist(22, 9, 15))
    assert in_window(SCHEDULE, NO_HOLIDAYS, _ist(22, 14, 59))
    assert not in_window(SCHEDULE, NO_HOLIDAYS, _ist(22, 15, 0))
    open_ended = ScriptSchedule(start_time=time(9, 15))
    assert in_window(open_ended, NO_HOLIDAYS, _ist(22, 23, 59))


def test_the_window_skips_other_weekdays_and_days_the_exchange_is_shut() -> None:
    tuesdays = ScriptSchedule(start_time=time(9, 0), weekdays=frozenset({1}))
    assert in_window(tuesdays, NO_HOLIDAYS, _ist(22, 10, 0))
    assert not in_window(tuesdays, NO_HOLIDAYS, _ist(23, 10, 0))

    holiday = MarketCalendar(
        years=frozenset({2026}),
        holidays=(Holiday(date(2026, 9, 22), "Test", frozenset({Exchange.NSE})),),
        special_sessions=(),
    )
    assert not in_window(SCHEDULE, holiday, _ist(22, 10, 0))
    mcx = ScriptSchedule(start_time=time(9, 0), exchange=Exchange.MCX)
    assert in_window(mcx, holiday, _ist(22, 10, 0))


def test_a_weekend_special_session_opens_the_window_on_a_weekend_day() -> None:
    sunday = ScriptSchedule(start_time=time(18, 0), weekdays=frozenset({6}))
    muhurat = MarketCalendar(
        years=frozenset({2026}),
        holidays=(),
        special_sessions=(
            SpecialSession(date(2026, 9, 27), "Muhurat", Exchange.NSE, time(18, 0), time(19, 0)),
        ),
    )
    assert in_window(sunday, muhurat, _ist(27, 18, 5))
    assert not in_window(sunday, NO_HOLIDAYS, _ist(27, 18, 5))


def test_stop_time_ends_a_run_started_before_it_whoever_started_it() -> None:
    started = _ist(22, 10, 0)
    assert stop_due(SCHEDULE, started, _ist(22, 14, 59)) is None
    assert stop_due(SCHEDULE, started, _ist(22, 15, 0)) == _ist(22, 15, 0)
    # Started after today's stop_time: runs until tomorrow's.
    late = _ist(22, 16, 0)
    assert stop_due(SCHEDULE, late, _ist(22, 23, 0)) is None
    assert stop_due(SCHEDULE, late, _ist(23, 9, 0)) is None
    assert stop_due(SCHEDULE, late, _ist(23, 15, 1)) == _ist(23, 15, 0)
    # Found after midnight, still past yesterday's.
    assert stop_due(SCHEDULE, started, _ist(23, 1, 0)) == _ist(22, 15, 0)
    assert stop_due(ScriptSchedule(start_time=time(9, 15)), started, _ist(23, 1, 0)) is None


def test_a_schedule_refuses_impossible_days_and_times() -> None:
    with pytest.raises(InvalidScriptError, match="0 \\(Monday\\) to 6 \\(Sunday\\)"):
        ScriptSchedule(start_time=time(9, 0), weekdays=frozenset())
    with pytest.raises(InvalidScriptError, match="0 \\(Monday\\) to 6 \\(Sunday\\)"):
        ScriptSchedule(start_time=time(9, 0), weekdays=frozenset({7}))
    with pytest.raises(InvalidScriptError, match="stop_time 09:00 must be after start_time 09:00"):
        ScriptSchedule(start_time=time(9, 0), stop_time=time(9, 0))
    ScriptSchedule(start_time=time(9, 0), stop_time=time(9, 1), weekdays=frozenset({0, 6}))


def test_limits_refuse_values_too_small_to_run_python() -> None:
    with pytest.raises(InvalidScriptError, match="at least 64 MB, got 63"):
        ScriptLimits(memory_mb=63)
    with pytest.raises(InvalidScriptError, match="at least 1 second, got 0"):
        ScriptLimits(cpu_seconds=0)
    assert ScriptLimits(memory_mb=64, cpu_seconds=1) == ScriptLimits(64, 1)
    assert ScriptLimits() == ScriptLimits(1024, 3600)


@pytest.mark.parametrize(
    ("returncode", "reason", "detail"),
    [
        (0, ScriptStopReason.EXITED, "exited with code 0"),
        (None, ScriptStopReason.EXITED, "exit code is unknown"),
        (1, ScriptStopReason.FAILED, "exited with code 1"),
        (-24, ScriptStopReason.CPU_LIMIT, "used up its CPU time"),
        (-9, ScriptStopReason.FAILED, "killed by SIGKILL"),
        (-99, ScriptStopReason.FAILED, "killed by signal 99"),
    ],
)
def test_how_a_run_ended_is_read_from_its_exit_status(
    returncode: int | None, reason: ScriptStopReason, detail: str
) -> None:
    found, why = exit_reason(returncode)
    assert found is reason
    assert detail in why
