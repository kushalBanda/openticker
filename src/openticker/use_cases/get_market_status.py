"""Is an exchange open now, and when is its next session (ADR 13 in docs/adr)."""

from datetime import datetime

from openticker.core.calendar.calendar import market_status
from openticker.core.calendar.models import MarketStatus
from openticker.ports.models import Exchange
from openticker.storage.calendar_file import load_calendar


def get_market_status(exchanges: list[Exchange], now: datetime) -> list[MarketStatus]:
    calendar = load_calendar()
    return [market_status(now, exchange, calendar) for exchange in exchanges]
