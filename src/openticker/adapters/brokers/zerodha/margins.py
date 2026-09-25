"""The margin Kite would block for orders, from its margin calculator. Nothing
is placed. One order goes to /margins/orders; several go to /margins/basket
with the account's positions considered, so hedges count (ADR 26 in
docs/adr)."""

from collections.abc import Sequence
from typing import Any

import httpx

from openticker.adapters.brokers.zerodha.auth import KITE_BASE_URL
from openticker.adapters.brokers.zerodha.market_data import kite_headers, kite_payload
from openticker.core.orders.models import OrderRequest
from openticker.ports.models import MarginRequirement

ORDERS_PATH = "/margins/orders"
BASKET_PATH = "/margins/basket"


def fetch_margin(
    api_key: str, access_token: str, orders: Sequence[OrderRequest]
) -> MarginRequirement:
    basket = len(orders) > 1
    path = BASKET_PATH if basket else ORDERS_PATH
    with httpx.Client(base_url=KITE_BASE_URL, timeout=30.0) as client:
        response = client.post(
            path,
            params={"consider_positions": "true"} if basket else None,
            json=[_to_kite_order(order) for order in orders],
            headers=kite_headers(api_key, access_token),
        )
    return _to_requirement(kite_payload(path, response)["data"])


def _to_kite_order(order: OrderRequest) -> dict[str, object]:
    return {
        "exchange": order.instrument.broker_exchange,
        "tradingsymbol": order.instrument.broker_symbol,
        "transaction_type": order.side.value,
        "variety": "regular",
        "product": order.product.value,
        "order_type": order.order_type.value,
        "quantity": order.quantity,
        "price": order.price or 0,
        "trigger_price": order.trigger_price or 0,
    }


def _to_requirement(data: Any) -> MarginRequirement:
    """A basket answers `initial` and `final`: `final` is what Kite's own
    basket shows as required, and the benefit is `initial` less `final`.
    `initial` is already partly offset, so placing the orders one by one
    would need more than `total` + `benefit`. One order answers a list of one."""
    if isinstance(data, dict):
        final: dict[str, Any] = data.get("final") or {}
        initial: dict[str, Any] = data.get("initial") or {}
        return MarginRequirement(
            total=_amount(final, "total"),
            span=_amount(final, "span"),
            exposure=_amount(final, "exposure"),
            option_premium=_amount(final, "option_premium"),
            benefit=_amount(initial, "total") - _amount(final, "total"),
        )
    orders: list[dict[str, Any]] = data or []
    return MarginRequirement(
        total=sum(_amount(order, "total") for order in orders),
        span=sum(_amount(order, "span") for order in orders),
        exposure=sum(_amount(order, "exposure") for order in orders),
        option_premium=sum(_amount(order, "option_premium") for order in orders),
        benefit=0.0,
    )


def _amount(values: dict[str, Any], key: str) -> float:
    return float(values.get(key) or 0)
