from datetime import date, datetime, time, timedelta

from openticker.core.calendar.models import Holiday, MarketCalendar
from openticker.core.risk.models import StrategyStopReason
from openticker.core.strategies.models import Schedule
from openticker.core.strategies.schedule import ENTRY_GRACE, entry_due, exit_due
from openticker.ports.models import EXCHANGE_TIMEZONE, Exchange
from tests.fixtures.calendar import NO_HOLIDAYS

TUESDAY = date(2026, 9, 22)
ENTRY = Schedule(entry_time=time(9, 20), exit_time=time(15, 0))


def ist(day: date, hour: int, minute: int) -> datetime:
    return datetime.combine(day, time(hour, minute), EXCHANGE_TIMEZONE)


def test_an_entry_is_due_from_entry_time_for_the_grace_period() -> None:
    at = ist(TUESDAY, 9, 20)

    assert entry_due(ENTRY, Exchange.NSE, NO_HOLIDAYS, at - timedelta(seconds=1)) is None
    assert entry_due(ENTRY, Exchange.NSE, NO_HOLIDAYS, at) == at
    assert entry_due(ENTRY, Exchange.NSE, NO_HOLIDAYS, at + ENTRY_GRACE - timedelta(seconds=1))
    assert entry_due(ENTRY, Exchange.NSE, NO_HOLIDAYS, at + ENTRY_GRACE) is None


def test_no_entry_without_an_entry_time() -> None:
    assert entry_due(Schedule(), Exchange.NSE, NO_HOLIDAYS, ist(TUESDAY, 9, 20)) is None


def test_no_entry_on_a_weekday_not_scheduled() -> None:
    mondays = Schedule(entry_time=time(9, 20), weekdays=frozenset({0}))

    assert entry_due(mondays, Exchange.NSE, NO_HOLIDAYS, ist(TUESDAY, 9, 20)) is None
    monday = TUESDAY - timedelta(days=1)
    assert entry_due(mondays, Exchange.NSE, NO_HOLIDAYS, ist(monday, 9, 20)) is not None


def test_no_entry_on_a_holiday() -> None:
    closed = MarketCalendar(
        years=frozenset({2026}),
        holidays=(Holiday(TUESDAY, "a holiday", frozenset({Exchange.NSE})),),
        special_sessions=(),
    )

    assert entry_due(ENTRY, Exchange.NSE, closed, ist(TUESDAY, 9, 20)) is None


def test_exit_time_closes_a_run_open_across_it() -> None:
    started = ist(TUESDAY, 9, 20)

    assert exit_due(ENTRY, started, set(), Exchange.NSE, NO_HOLIDAYS, ist(TUESDAY, 14, 59)) is None
    assert exit_due(ENTRY, started, set(), Exchange.NSE, NO_HOLIDAYS, ist(TUESDAY, 15, 0)) == (
        StrategyStopReason.SCHEDULE,
        "exit_time 15:00",
    )


def test_exit_time_leaves_a_run_started_after_it_until_the_next_day() -> None:
    started = ist(TUESDAY, 15, 5)

    assert exit_due(ENTRY, started, set(), Exchange.NSE, NO_HOLIDAYS, ist(TUESDAY, 15, 10)) is None
    wednesday = TUESDAY + timedelta(days=1)
    assert exit_due(ENTRY, started, set(), Exchange.NSE, NO_HOLIDAYS, ist(wednesday, 15, 0))


def test_nothing_closes_on_a_day_the_market_is_shut() -> None:
    saturday = date(2026, 9, 26)

    assert (
        exit_due(ENTRY, ist(TUESDAY, 9, 20), set(), Exchange.NSE, NO_HOLIDAYS, ist(saturday, 15, 0))
        is None
    )


def test_expiry_day_closes_at_exit_time() -> None:
    positional = Schedule(exit_time=time(15, 0))
    started = ist(TUESDAY - timedelta(days=1), 10, 0)

    assert exit_due(
        positional, started, {TUESDAY}, Exchange.NSE, NO_HOLIDAYS, ist(TUESDAY, 15, 0)
    ) == (StrategyStopReason.EXPIRY, "expiry day exit 15:00")


def test_expiry_day_without_exit_time_closes_at_the_square_off() -> None:
    positional = Schedule()
    started = ist(TUESDAY - timedelta(days=1), 10, 0)

    def due(hour: int, minute: int) -> tuple[StrategyStopReason, str] | None:
        return exit_due(
            positional, started, {TUESDAY}, Exchange.NSE, NO_HOLIDAYS, ist(TUESDAY, hour, minute)
        )

    assert due(15, 14) is None
    assert due(15, 15) == (StrategyStopReason.EXPIRY, "expiry day exit 15:15")


def test_expiry_day_is_left_to_settlement_when_asked() -> None:
    held = Schedule(exit_on_expiry=False)

    assert (
        exit_due(
            held, ist(TUESDAY, 9, 20), {TUESDAY}, Exchange.NSE, NO_HOLIDAYS, ist(TUESDAY, 15, 20)
        )
        is None
    )


def test_a_contract_expiring_another_day_is_not_closed() -> None:
    positional = Schedule()
    started = ist(TUESDAY, 9, 20)
    later = {TUESDAY + timedelta(days=7)}

    assert (
        exit_due(positional, started, later, Exchange.NSE, NO_HOLIDAYS, ist(TUESDAY, 15, 20))
        is None
    )


def test_an_exit_time_missed_while_the_daemon_was_down_closes_the_run_next_morning() -> None:
    monday = TUESDAY - timedelta(days=1)
    friday = monday - timedelta(days=3)

    assert exit_due(
        ENTRY, ist(monday, 10, 0), set(), Exchange.NSE, NO_HOLIDAYS, ist(TUESDAY, 9, 15)
    ) == (StrategyStopReason.SCHEDULE, "exit_time 15:00")
    assert exit_due(  # over a weekend
        ENTRY, ist(friday, 10, 0), set(), Exchange.NSE, NO_HOLIDAYS, ist(monday, 9, 15)
    ) == (StrategyStopReason.SCHEDULE, "exit_time 15:00")


def test_a_weekend_is_not_an_exit_time() -> None:
    monday = TUESDAY - timedelta(days=1)
    friday = monday - timedelta(days=3)

    assert (
        exit_due(ENTRY, ist(friday, 15, 5), set(), Exchange.NSE, NO_HOLIDAYS, ist(monday, 9, 15))
        is None
    )
