"""The order path every entry point shares: validate -> risk check -> order
adapter -> events. The adapter is the sandbox (ADR 11 in docs/adr)."""

from datetime import datetime

from openticker.core.calendar.calendar import (
    intraday_allowed,
    market_status,
    session_hours,
    square_off_at,
)
from openticker.core.calendar.models import MarketCalendar
from openticker.core.orders.models import OrderRequest, OrderResult, OrderStatus
from openticker.core.orders.validation import validate_order
from openticker.core.risk.models import BreachReason, PositionRisk
from openticker.core.risk.position import evaluate_position
from openticker.events.bus import EventPublisher
from openticker.events.types import OrderFailed, OrderFilled, OrderPlaced, RiskBreached
from openticker.ports.broker_port import BrokerPort
from openticker.ports.errors import BrokerError
from openticker.ports.models import EXCHANGE_TIMEZONE, Product, Side


def place_order(
    request: OrderRequest,
    broker: BrokerPort,
    events: EventPublisher,
    capital_cap: float | None,
    calendar: MarketCalendar,
    now: datetime,
    check_session: bool = True,
) -> OrderResult:
    """`capital_cap` is the most one position may be worth after this order.
    It never blocks an order that only reduces a position: a cap must not trap
    anyone in a trade. An order needs its exchange open: outside the session
    the last price is yesterday's, not one anyone could trade at. After the
    intraday square-off, MIS orders may only reduce a position, so one the
    daemon didn't close can still be closed by hand. `check_session` is off
    only for the square-off itself, which may have to close a position the
    daemon missed."""
    symbol = request.instrument.symbol
    validation = validate_order(request, now.astimezone(EXCHANGE_TIMEZONE).date())
    if not validation.valid:
        return _failed(events, request, OrderStatus.REJECTED, validation.reason or "invalid order")
    closed = _market_closed(request, calendar, now) if check_session else None
    if closed is not None:
        return _failed(events, request, OrderStatus.REJECTED, closed)

    try:
        if (
            check_session
            and _past_intraday_cutoff(request, calendar, now)
            and not _only_reduces(request, broker)
        ):
            return _failed(
                events, request, OrderStatus.REJECTED, _cutoff_reason(request, calendar, now)
            )
        if capital_cap is not None:
            breach = _capital_cap_breach(request, broker, capital_cap)
            if breach is not None:
                events.publish(
                    RiskBreached(symbol=symbol, reason=BreachReason.CAPITAL_CAP, detail=breach)
                )
                return OrderResult(status=OrderStatus.REJECTED, broker_order_id=None, reason=breach)
        result = broker.place_order(request)
    except BrokerError as exc:
        return _failed(events, request, OrderStatus.FAILED, str(exc))

    if result.status is OrderStatus.PENDING and result.broker_order_id is not None:
        events.publish(
            OrderPlaced(
                order_id=result.broker_order_id,
                symbol=symbol,
                side=request.side.value,
                quantity=request.quantity,
                triggered_by=request.triggered_by,
            )
        )
        return result
    if result.status is not OrderStatus.FILLED or result.broker_order_id is None:
        events.publish(
            OrderFailed(
                symbol=symbol,
                reason=result.reason or result.status.value,
                triggered_by=request.triggered_by,
            )
        )
        return result
    events.publish(
        OrderPlaced(
            order_id=result.broker_order_id,
            symbol=symbol,
            side=request.side.value,
            quantity=request.quantity,
            triggered_by=request.triggered_by,
        )
    )
    if result.fill_price is not None:
        events.publish(
            OrderFilled(
                order_id=result.broker_order_id,
                symbol=symbol,
                side=request.side.value,
                quantity=request.quantity,
                price=result.fill_price,
                triggered_by=request.triggered_by,
            )
        )
    return result


def _market_closed(request: OrderRequest, calendar: MarketCalendar, now: datetime) -> str | None:
    exchange = request.instrument.exchange
    status = market_status(now, exchange, calendar)
    if not status.is_open:
        opens = status.session.opens_at.strftime("%a %d %b %H:%M")
        return f"{exchange} is closed ({status.closed_reason}); it next opens {opens} IST"
    return None


def _past_intraday_cutoff(request: OrderRequest, calendar: MarketCalendar, now: datetime) -> bool:
    return request.product is Product.MIS and not intraday_allowed(
        now, request.instrument.exchange, calendar
    )


def _cutoff_reason(request: OrderRequest, calendar: MarketCalendar, now: datetime) -> str:
    exchange = request.instrument.exchange
    hours = session_hours(now.astimezone(EXCHANGE_TIMEZONE).date(), exchange, calendar)
    cutoff = square_off_at(hours).strftime("%H:%M") if hours else "the square-off"
    return (
        f"after the {cutoff} square-off, intraday (MIS) orders on {exchange} may only reduce "
        "a position; use NRML or CNC to open one"
    )


def _held_after(request: OrderRequest, broker: BrokerPort) -> tuple[int, int]:
    """The position in this instrument and product now, and after the order."""
    held = sum(
        position.quantity
        for position in broker.get_positions()
        if position.instrument.symbol == request.instrument.symbol
        and position.instrument.exchange == request.instrument.exchange
        and position.product == request.product
    )
    return held, held + (request.quantity if request.side is Side.BUY else -request.quantity)


def _only_reduces(request: OrderRequest, broker: BrokerPort) -> bool:
    held, after = _held_after(request, broker)
    return held * after >= 0 and abs(after) <= abs(held)


def _capital_cap_breach(
    request: OrderRequest, broker: BrokerPort, capital_cap: float
) -> str | None:
    if _only_reduces(request, broker):
        return None
    _, after = _held_after(request, broker)
    price = broker.get_quote(request.instrument).last_price
    decision = evaluate_position(
        PositionRisk(
            side=Side.BUY if after > 0 else Side.SELL,
            entry_price=price,
            quantity=abs(after),
            initial_sl=None,
            current_sl=None,
            target=None,
            highest_price=None,
            lowest_price=None,
            capital_cap=capital_cap,
        ),
        price,
    )
    return decision.detail if decision.reason is BreachReason.CAPITAL_CAP else None


def _failed(
    events: EventPublisher, request: OrderRequest, status: OrderStatus, reason: str
) -> OrderResult:
    events.publish(
        OrderFailed(
            symbol=request.instrument.symbol, reason=reason, triggered_by=request.triggered_by
        )
    )
    return OrderResult(status=status, broker_order_id=None, reason=reason)
