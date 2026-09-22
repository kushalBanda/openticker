"""The order path every entry point shares: validate -> risk check -> order
adapter -> events. The adapter is the sandbox (ADR 11 in docs/adr)."""

from datetime import datetime

from openticker.core.orders.models import OrderRequest, OrderResult, OrderStatus
from openticker.core.orders.validation import validate_order
from openticker.core.risk.models import BreachReason, PositionRisk
from openticker.core.risk.position import evaluate_position
from openticker.events.bus import EventPublisher
from openticker.events.types import OrderFailed, OrderFilled, OrderPlaced, RiskBreached
from openticker.ports.broker_port import BrokerPort
from openticker.ports.errors import BrokerError
from openticker.ports.models import EXCHANGE_TIMEZONE, Side


def place_order(
    request: OrderRequest,
    broker: BrokerPort,
    events: EventPublisher,
    capital_cap: float | None,
    now: datetime,
) -> OrderResult:
    """`capital_cap` is the most one position may be worth after this order.
    It never blocks an order that only reduces a position: a cap must not trap
    anyone in a trade."""
    symbol = request.instrument.symbol
    validation = validate_order(request, now.astimezone(EXCHANGE_TIMEZONE).date())
    if not validation.valid:
        return _failed(events, request, OrderStatus.REJECTED, validation.reason or "invalid order")

    try:
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


def _capital_cap_breach(
    request: OrderRequest, broker: BrokerPort, capital_cap: float
) -> str | None:
    held = sum(
        position.quantity
        for position in broker.get_positions()
        if position.instrument.symbol == request.instrument.symbol
        and position.instrument.exchange == request.instrument.exchange
        and position.product == request.product
    )
    after = held + (request.quantity if request.side is Side.BUY else -request.quantity)
    if held * after >= 0 and abs(after) <= abs(held):
        return None  # only reduces the position
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
