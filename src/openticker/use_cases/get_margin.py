"""The margin the broker would block for a set of orders, hedge benefit
included. Nothing is placed, so it works with the market closed. It is the
broker's figure: the sandbox blocks by its own rule (ADR 11, ADR 26 in
docs/adr)."""

from collections.abc import Sequence
from datetime import datetime

from openticker.core.orders.models import OrderRequest
from openticker.core.orders.validation import validate_order
from openticker.ports.broker_port import BrokerPort
from openticker.ports.models import EXCHANGE_TIMEZONE, MarginRequirement
from openticker.use_cases.errors import BatchTooLargeError
from openticker.use_cases.place_basket import BasketOrder
from openticker.use_cases.resolve_instrument import UnknownInstrumentError, resolve_instrument

# Keeps every answer bounded (ADR 8 in docs/adr).
MAX_MARGIN_ORDERS = 50


class InvalidMarginOrderError(ValueError):
    """An order the broker couldn't price; the message names which."""


def get_margin(
    broker: BrokerPort, orders: Sequence[BasketOrder], now: datetime
) -> MarginRequirement:
    """Every order must be known and well formed: a total missing one leg of
    a hedged set would be wrong, so nothing is priced until all are."""
    if len(orders) > MAX_MARGIN_ORDERS:
        raise BatchTooLargeError(f"{len(orders)} orders; at most {MAX_MARGIN_ORDERS}")
    today = now.astimezone(EXCHANGE_TIMEZONE).date()
    requests: list[OrderRequest] = []
    for index, order in enumerate(orders, 1):
        try:
            instrument = resolve_instrument(order.symbol, order.exchange.value)
        except UnknownInstrumentError as exc:
            raise UnknownInstrumentError(f"order {index}: {exc}") from exc
        request = OrderRequest(
            instrument=instrument,
            side=order.side,
            quantity=order.quantity,
            product=order.product,
            order_type=order.order_type,
            price=order.price,
            trigger_price=order.trigger_price,
            triggered_by="margin",
        )
        validation = validate_order(request, today)
        if not validation.valid:
            raise InvalidMarginOrderError(f"order {index} ({order.symbol}): {validation.reason}")
        requests.append(request)
    return broker.get_margin(requests)
