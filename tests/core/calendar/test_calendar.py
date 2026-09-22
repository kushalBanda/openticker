from datetime import date, datetime, time

import pytest

from openticker.core.calendar.calendar import (
    CalendarError,
    market_status,
    next_session,
    parse_calendar,
    session_hours,
)
from openticker.core.calendar.models import Holiday, MarketCalendar, SpecialSession
from openticker.ports.models import EXCHANGE_TIMEZONE, Exchange

EQUITY = frozenset({Exchange.NSE, Exchange.BSE, Exchange.NFO, Exchange.BFO})
GANDHI_JAYANTI = date(2026, 10, 2)  # Friday
HOLI = date(2026, 3, 3)  # Tuesday
CALENDAR = MarketCalendar(
    years=frozenset({2026}),
    holidays=(
        Holiday(GANDHI_JAYANTI, "Mahatma Gandhi Jayanti", EQUITY | {Exchange.MCX}),
        Holiday(HOLI, "Holi", EQUITY | {Exchange.MCX}),
    ),
    special_sessions=(
        SpecialSession(HOLI, "Holi (evening session only)", Exchange.MCX, time(17, 0), None),
        SpecialSession(date(2026, 11, 8), "Muhurat trading", Exchange.NSE, time(18), time(19)),
    ),
)


def ist(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=EXCHANGE_TIMEZONE)


def test_calendar_skips_holiday_and_weekend() -> None:
    assert session_hours(GANDHI_JAYANTI, Exchange.NSE, CALENDAR) is None
    assert session_hours(date(2026, 9, 26), Exchange.NSE, CALENDAR) is None  # Saturday
    hours = session_hours(date(2026, 9, 22), Exchange.NSE, CALENDAR)
    assert hours is not None
    assert (hours.opens_at, hours.closes_at) == (ist(2026, 9, 22, 9, 15), ist(2026, 9, 22, 15, 30))


def test_mcx_trades_late_and_later_while_the_us_is_on_standard_time() -> None:
    summer = session_hours(date(2026, 9, 22), Exchange.MCX, CALENDAR)
    winter = session_hours(date(2026, 12, 1), Exchange.MCX, CALENDAR)

    assert summer is not None and summer.closes_at == ist(2026, 9, 22, 23, 30)
    assert winter is not None and winter.closes_at == ist(2026, 12, 1, 23, 55)


def test_special_session_overrides_a_holiday_and_a_weekend() -> None:
    evening = session_hours(HOLI, Exchange.MCX, CALENDAR)
    muhurat = session_hours(date(2026, 11, 8), Exchange.NSE, CALENDAR)  # Sunday

    assert evening is not None and evening.opens_at == ist(2026, 3, 3, 17, 0)
    assert evening.closes_at == ist(2026, 3, 3, 23, 55)  # before the US switches, 8 Mar
    assert session_hours(HOLI, Exchange.NSE, CALENDAR) is None
    assert muhurat is not None and muhurat.name == "Muhurat trading"
    assert session_hours(date(2026, 11, 8), Exchange.BSE, CALENDAR) is None


def test_next_session_skips_holiday_and_weekend() -> None:
    after_close = ist(2026, 10, 1, 16, 0)  # Thursday; Friday is a holiday

    assert next_session(after_close, Exchange.NSE, CALENDAR).day == date(2026, 10, 5)
    assert next_session(ist(2026, 9, 22, 10, 0), Exchange.NSE, CALENDAR).day == date(2026, 9, 22)


@pytest.mark.parametrize(
    ("now", "is_open", "reason"),
    [
        (ist(2026, 9, 22, 10, 0), True, None),
        (ist(2026, 9, 22, 9, 14), False, "before the session"),
        (ist(2026, 9, 22, 15, 30), False, "after the session"),
        (ist(2026, 9, 26, 11, 0), False, "weekend"),
        (ist(2026, 10, 2, 11, 0), False, "Mahatma Gandhi Jayanti"),
    ],
)
def test_market_status_says_why_it_is_closed(
    now: datetime, is_open: bool, reason: str | None
) -> None:
    status = market_status(now, Exchange.NSE, CALENDAR)

    assert (status.is_open, status.closed_reason) == (is_open, reason)
    assert status.holidays_known


def test_a_year_the_holiday_list_does_not_cover_is_flagged() -> None:
    status = market_status(ist(2027, 1, 5, 10, 0), Exchange.NSE, CALENDAR)

    assert status.is_open and not status.holidays_known


def test_parse_calendar_rejects_a_malformed_file() -> None:
    with pytest.raises(CalendarError, match="malformed"):
        parse_calendar({"years": [2026], "holidays": [{"date": "2026-13-01", "name": "x"}]})
    with pytest.raises(CalendarError, match="malformed"):
        parse_calendar(
            {
                "years": [2026],
                "holidays": [{"date": "2026-01-26", "name": "x", "exchanges": ["NYSE"]}],
            }
        )


def test_a_holiday_closes_only_the_exchanges_it_lists() -> None:
    equity_only = MarketCalendar(
        years=frozenset({2026}),
        holidays=(Holiday(date(2026, 9, 22), "Equity holiday", EQUITY),),
        special_sessions=(),
    )

    assert session_hours(date(2026, 9, 22), Exchange.NSE, equity_only) is None
    assert session_hours(date(2026, 9, 22), Exchange.MCX, equity_only) is not None
