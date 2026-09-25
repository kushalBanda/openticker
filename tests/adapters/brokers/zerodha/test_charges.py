from dataclasses import replace
from types import TracebackType
from typing import Any, Self

import httpx
import pytest

from openticker.adapters.brokers.zerodha.charges import fetch_charges
from openticker.core.orders.charge_check import ChargeSample
from openticker.ports.errors import BrokerError, BrokerSessionError
from openticker.ports.models import Exchange, InstrumentType, Product, Side
from tests.fixtures.fake_broker import FAKE_INSTRUMENT

OPTION = replace(
    FAKE_INSTRUMENT,
    symbol="NIFTY29SEP2625000CE",
    broker_symbol="NIFTY2592925000CE",
    exchange=Exchange.NFO,
    broker_exchange="NFO",
    instrument_type=InstrumentType.CE,
    lot_size=65,
)
SELL = ChargeSample(OPTION, Side.SELL, 65, Product.NRML, 86.7)

# Kite's answer for SELL, as its contract note gave it on 2026-09-25.
KITE_SELL = {
    "transaction_type": "SELL",
    "tradingsymbol": "NIFTY2592925000CE",
    "exchange": "NFO",
    "quantity": 65,
    "price": 86.7,
    "charges": {
        "transaction_tax": 8.45,
        "transaction_tax_type": "stt",
        "exchange_turnover_charge": 2.0,
        "sebi_turnover_charge": 0.01,
        "brokerage": 20,
        "stamp_duty": 0,
        "gst": {"igst": 3.96, "cgst": 0, "sgst": 0, "total": 3.96},
        "total": 34.42,
    },
}


class _FakeClient:
    def __init__(self, response: httpx.Response) -> None:
        self._response = response
        self.posts: list[tuple[str, Any]] = []

    def __call__(self, base_url: str, timeout: float) -> Self:
        return self

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        pass

    def post(self, path: str, json: Any, headers: dict[str, str]) -> httpx.Response:
        self.posts.append((path, json))
        return self._response


def _install(monkeypatch: pytest.MonkeyPatch, response: httpx.Response) -> _FakeClient:
    client = _FakeClient(response)
    monkeypatch.setattr(httpx, "Client", client)
    return client


def _ok(data: Any) -> httpx.Response:
    return httpx.Response(200, json={"status": "success", "data": data})


def test_orders_go_as_executed_in_the_brokers_names(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _install(monkeypatch, _ok([KITE_SELL]))

    fetch_charges("key", "token", [SELL])

    assert client.posts == [
        (
            "/charges/orders",
            [
                {
                    "order_id": "0",
                    "exchange": "NFO",
                    "tradingsymbol": "NIFTY2592925000CE",
                    "transaction_type": "SELL",
                    "variety": "regular",
                    "product": "NRML",
                    "order_type": "MARKET",
                    "quantity": 65,
                    "average_price": 86.7,
                }
            ],
        )
    ]


def test_kites_items_map_to_ours(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _ok([KITE_SELL]))

    [charges] = fetch_charges("key", "token", [SELL])

    assert charges.items == {
        "brokerage": 20.0,
        "transaction_tax": 8.45,
        "exchange_txn": 2.0,
        "sebi": 0.01,
        "stamp_duty": 0.0,
        "gst": 3.96,
    }
    assert charges.total == 34.42


def test_an_answer_short_of_the_orders_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _ok([KITE_SELL]))

    with pytest.raises(BrokerError, match="priced 1 of 2"):
        fetch_charges("key", "token", [SELL, replace(SELL, side=Side.BUY)])


def test_a_rejected_session_says_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, httpx.Response(403, json={"error_type": "TokenException"}))

    with pytest.raises(BrokerSessionError, match="reconnect"):
        fetch_charges("key", "token", [SELL])
