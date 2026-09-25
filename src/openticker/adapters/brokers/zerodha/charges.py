"""What Kite charges for orders as executed, from its virtual contract note
(`POST /charges/orders`). Nothing is placed. Used only to check the shipped
charge rates, never during a fill (ADR 28 in docs/adr)."""

from collections.abc import Sequence
from typing import Any

import httpx

from openticker.adapters.brokers.zerodha.auth import KITE_BASE_URL
from openticker.adapters.brokers.zerodha.market_data import (
    KiteApiError,
    kite_headers,
    kite_payload,
)
from openticker.core.orders.charge_check import ChargeSample
from openticker.core.orders.charges import Charges

CHARGES_PATH = "/charges/orders"

# Kite's name for each charge, and ours (src/openticker/data/charges.json).
_KEYS = {
    "brokerage": "brokerage",
    "transaction_tax": "transaction_tax",
    "exchange_turnover_charge": "exchange_txn",
    "sebi_turnover_charge": "sebi",
    "stamp_duty": "stamp_duty",
}


def fetch_charges(api_key: str, access_token: str, orders: Sequence[ChargeSample]) -> list[Charges]:
    with httpx.Client(base_url=KITE_BASE_URL, timeout=30.0) as client:
        response = client.post(
            CHARGES_PATH,
            json=[_to_kite_order(index, order) for index, order in enumerate(orders)],
            headers=kite_headers(api_key, access_token),
        )
    answers: list[dict[str, Any]] = kite_payload(CHARGES_PATH, response)["data"] or []
    if len(answers) != len(orders):
        raise KiteApiError(f"Kite {CHARGES_PATH} priced {len(answers)} of {len(orders)} orders")
    return [_to_charges(answer.get("charges") or {}) for answer in answers]


def _to_kite_order(index: int, order: ChargeSample) -> dict[str, object]:
    return {
        "order_id": str(index),
        "exchange": order.instrument.broker_exchange,
        "tradingsymbol": order.instrument.broker_symbol,
        "transaction_type": order.side.value,
        "variety": "regular",
        "product": order.product.value,
        "order_type": "MARKET",
        "quantity": order.quantity,
        "average_price": order.price,
    }


def _to_charges(charges: dict[str, Any]) -> Charges:
    items = {ours: float(charges.get(kite) or 0) for kite, ours in _KEYS.items()}
    gst: dict[str, Any] = charges.get("gst") or {}
    items["gst"] = float(gst.get("total") or 0)
    return Charges(items=items)
