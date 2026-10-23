"""What the desk manager's lines hold out now (ADR 46): read by the daemon
before a scheduled entry or a scheduled script start, and by the alert URL
before an entry."""

from datetime import datetime

from openticker.core.agents.manager import LineKey, LineKind, held
from openticker.core.calendar.models import MarketCalendar
from openticker.storage.sqlite import manager_repo


def held_now(calendar: MarketCalendar, now: datetime) -> frozenset[str]:
    """Line keys ("strategy:<id>", "script:<id>") held out at `now`."""
    return held(manager_repo.get_state(), manager_repo.lines(), now, calendar)


def strategy_held(strategy_id: str, held_out: frozenset[str]) -> bool:
    return str(LineKey(LineKind.STRATEGY, strategy_id)) in held_out


def script_held(script_id: str, held_out: frozenset[str]) -> bool:
    return str(LineKey(LineKind.SCRIPT, script_id)) in held_out
