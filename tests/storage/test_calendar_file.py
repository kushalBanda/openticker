import json
from datetime import date
from pathlib import Path

import pytest

from openticker.core.calendar.calendar import CalendarError, session_hours
from openticker.ports.models import Exchange
from openticker.storage.calendar_file import load_calendar

# NSE's 2026 trading holidays on weekdays, from its annual circular plus the
# 15 January circular for the Maharashtra municipal elections.
NSE_2026 = {
    "2026-01-15", "2026-01-26", "2026-03-03", "2026-03-26", "2026-03-31", "2026-04-03",
    "2026-04-14", "2026-05-01", "2026-05-28", "2026-06-26", "2026-09-14", "2026-10-02",
    "2026-10-20", "2026-11-10", "2026-11-24", "2026-12-25",
}  # fmt: skip


def test_shipped_file_has_every_2026_exchange_holiday() -> None:
    calendar = load_calendar()

    for exchange in (Exchange.NSE, Exchange.BSE, Exchange.NFO, Exchange.BFO):
        closed = {
            str(h.day) for h in calendar.holidays if exchange in h.exchanges and h.day.year == 2026
        }
        assert closed == NSE_2026, exchange


def test_mcx_keeps_its_evening_session_on_most_equity_holidays() -> None:
    calendar = load_calendar()

    assert session_hours(date(2026, 1, 26), Exchange.MCX, calendar) is None  # Republic Day
    holi = session_hours(date(2026, 3, 3), Exchange.MCX, calendar)
    new_year = session_hours(date(2026, 1, 1), Exchange.MCX, calendar)
    assert holi is not None and holi.opens_at.hour == 17
    assert new_year is not None and new_year.closes_at.hour == 17


def test_a_file_in_openticker_home_replaces_the_shipped_one(tmp_path: Path) -> None:
    (tmp_path / "holidays.json").write_text(
        json.dumps({"years": [2027], "holidays": [], "special_sessions": []})
    )

    assert load_calendar().years == frozenset({2027})


def test_a_broken_override_names_the_file(tmp_path: Path) -> None:
    (tmp_path / "holidays.json").write_text("{not json")

    with pytest.raises(CalendarError, match="holidays.json"):
        load_calendar()
