"""Loads the market calendar: the holiday file shipped with the package, or
`$OPENTICKER_HOME/holidays.json` when present, which replaces it entirely
(ADR 13 in docs/adr)."""

import json
from importlib.resources import files

from openticker.core.calendar.calendar import CalendarError, parse_calendar
from openticker.core.calendar.models import MarketCalendar
from openticker.storage.sqlite.engine import get_data_dir


def load_calendar() -> MarketCalendar:
    override = get_data_dir() / "holidays.json"
    if override.exists():
        source, text = str(override), override.read_text()
    else:
        source, text = (
            "the shipped holiday file",
            files("openticker").joinpath("data/holidays.json").read_text(),
        )
    try:
        return parse_calendar(json.loads(text))
    except (json.JSONDecodeError, CalendarError) as exc:
        raise CalendarError(f"{source}: {exc}") from exc
