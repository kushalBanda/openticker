"""Closes intraday (MIS) positions at the square-off, 15 minutes before the
session's close (ADR 11 in docs/adr). A position the daemon finds open at any
other time outside the intraday window (it wasn't running at the square-off)
is closed then, at the latest price. A contract past its expiry can't be
traded any more, so it is left for settlement rather than retried."""

from datetime import datetime

from openticker.core.calendar.calendar import intraday_allowed
from openticker.core.calendar.models import MarketCalendar
from openticker.core.orders.models import OrderRequest, OrderResult, OrderType
from openticker.events.bus import EventPublisher
from openticker.ports.broker_port import BrokerPort
from openticker.ports.models import EXCHANGE_TIMEZONE, Product, Side
from openticker.ports.sandbox_port import SandboxPort
from openticker.use_cases.place_order import place_order

SQUARE_OFF_TRIGGER = "square-off"


def square_off_intraday(
    broker: BrokerPort,
    sandbox: SandboxPort,
    events: EventPublisher,
    calendar: MarketCalendar,
    now: datetime,
) -> list[OrderResult]:
    results: list[OrderResult] = []
    today = now.astimezone(EXCHANGE_TIMEZONE).date()
    for position in sandbox.open_positions():
        if position.product is not Product.MIS:
            continue
        if intraday_allowed(now, position.instrument.exchange, calendar):
            continue
        expiry = position.instrument.expiry
        if expiry is not None and expiry < today:
            continue
        request = OrderRequest(
            instrument=position.instrument,
            side=Side.SELL if position.quantity > 0 else Side.BUY,
            quantity=abs(position.quantity),
            product=Product.MIS,
            order_type=OrderType.MARKET,
            price=None,
            triggered_by=SQUARE_OFF_TRIGGER,
        )
        results.append(
            place_order(request, broker, events, None, calendar, now, check_session=False)
        )
    return results
