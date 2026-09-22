"""What an expired futures or options contract settles at, and when. Pure
(ADR 11 in docs/adr).

Index derivatives settle in cash on the underlying's closing price on expiry
day: a future at that price, an option at its intrinsic value. Stock F&O are
physically settled on the exchange; the sandbox settles them in cash the same
way, which leaves the same profit or loss without delivering shares.
"""

from datetime import date, datetime, time, timedelta

from openticker.core.calendar.calendar import session_hours
from openticker.core.calendar.models import MarketCalendar
from openticker.ports.models import EXCHANGE_TIMEZONE, Instrument, InstrumentType

# The day's close is final some minutes after the session ends.
SETTLEMENT_DELAY = timedelta(minutes=15)


def settlement_price(contract: Instrument, underlying_close: float) -> float:
    """In rupees and paise: 23118.60 - 23000 is 118.60, not 118.5999..."""
    strike = contract.strike or 0.0
    match contract.instrument_type:
        case InstrumentType.CE:
            return round(max(0.0, underlying_close - strike), 2)
        case InstrumentType.PE:
            return round(max(0.0, strike - underlying_close), 2)
    return underlying_close


def settles_at(contract: Instrument, expiry: date, calendar: MarketCalendar) -> datetime:
    """When an expired contract can be settled: once the close of its expiry
    day is final. An expiry day with no session settles at its end."""
    hours = session_hours(expiry, contract.exchange, calendar)
    if hours is None:
        return datetime.combine(expiry + timedelta(days=1), time(0), EXCHANGE_TIMEZONE)
    return hours.closes_at + SETTLEMENT_DELAY
