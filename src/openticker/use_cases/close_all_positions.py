"""Close every open sandbox position at the market (ADR 11 in docs/adr).
Strategies are not stopped: each runner finds its legs already flat when it
next exits, and a signal strategy may enter again on its next alert; the
kill switch is what stops that."""

from datetime import datetime

from openticker.core.calendar.models import MarketCalendar
from openticker.core.orders.models import OrderResult
from openticker.events.bus import EventPublisher
from openticker.ports.models import Position
from openticker.ports.sandbox_port import OrderSandbox
from openticker.use_cases.close_position import close_held


def close_all_positions(
    sandbox: OrderSandbox,
    events: EventPublisher,
    calendar: MarketCalendar,
    now: datetime,
    triggered_by: str,
) -> list[tuple[Position, OrderResult]]:
    """One result per position; one that can't close (exchange closed, no
    fresh price, expired) says why and the rest still close. Prices come
    from one quotes call."""
    positions = sandbox.open_positions()
    if not positions:
        return []
    quotes = {
        (quote.instrument.exchange, quote.instrument.symbol): quote
        for quote in sandbox.get_quotes([position.instrument for position in positions])
    }
    return [
        (
            position,
            close_held(
                sandbox,
                position,
                quotes.get((position.instrument.exchange, position.instrument.symbol)),
                events,
                calendar,
                now,
                triggered_by,
            ),
        )
        for position in positions
    ]
