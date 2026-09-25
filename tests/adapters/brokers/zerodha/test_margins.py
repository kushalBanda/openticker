from dataclasses import replace
from types import TracebackType
from typing import Any, Self

import httpx
import pytest

from openticker.adapters.brokers.zerodha.margins import fetch_margin
from openticker.core.orders.models import OrderRequest, OrderType
from openticker.ports.errors import BrokerSessionError
from openticker.ports.models import Exchange, InstrumentType, Product, Side
from tests.fixtures.fake_broker import FAKE_INSTRUMENT

OPTION = replace(
    FAKE_INSTRUMENT,
    symbol="NIFTY29SEP2625000CE",
    broker_symbol="NIFTY2592925000CE",
    exchange=Exchange.NFO,
    broker_exchange="NFO",
    instrument_type=InstrumentType.CE,
    lot_size=75,
)


class _FakeClient:
    """Stands in for httpx.Client; answers each POST with the next queued response."""

    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = responses
        self.posts: list[tuple[str, dict[str, str] | None, Any]] = []

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

    def post(
        self, path: str, params: dict[str, str] | None, json: Any, headers: dict[str, str]
    ) -> httpx.Response:
        self.posts.append((path, params, json))
        return self._responses.pop(0)


def _install(monkeypatch: pytest.MonkeyPatch, *responses: httpx.Response) -> _FakeClient:
    client = _FakeClient(list(responses))
    monkeypatch.setattr(httpx, "Client", client)
    return client


def _ok(data: Any) -> httpx.Response:
    return httpx.Response(200, json={"status": "success", "data": data})


def _order(side: Side, order_type: OrderType = OrderType.MARKET, **kw: Any) -> OrderRequest:
    return OrderRequest(OPTION, side, 75, Product.NRML, order_type, None, "margin", **kw)


def test_single_order_uses_orders_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _install(
        monkeypatch,
        _ok([{"span": 100000.5, "exposure": 20000, "option_premium": 0, "total": 120000.5}]),
    )

    margin = fetch_margin("key", "token", [_order(Side.SELL)])

    [(path, params, body)] = client.posts
    assert (path, params) == ("/margins/orders", None)
    assert body[0]["tradingsymbol"] == "NIFTY2592925000CE"  # the broker's symbol
    assert (margin.total, margin.span, margin.exposure, margin.benefit) == (
        120000.5,
        100000.5,
        20000.0,
        0.0,
    )


def test_several_use_basket_with_consider_positions(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _install(
        monkeypatch,
        _ok(
            {
                "initial": {"total": 258139, "span": 179780},
                "final": {
                    "total": 191119,
                    "span": 120000,
                    "exposure": 60000,
                    "option_premium": 11119,
                },
                "orders": [],
            }
        ),
    )

    margin = fetch_margin("key", "token", [_order(Side.BUY), _order(Side.SELL)])

    [(path, params, body)] = client.posts
    assert (path, params, len(body)) == ("/margins/basket", {"consider_positions": "true"}, 2)
    assert (margin.total, margin.span, margin.option_premium) == (191119, 120000, 11119)
    assert margin.benefit == 258139 - 191119


def test_kite_order_body_maps_types_and_products(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _install(monkeypatch, _ok([{"total": 1}]))

    fetch_margin("key", "token", [_order(Side.SELL, OrderType.SL_M, trigger_price=95.5)])

    assert client.posts[0][2] == [
        {
            "exchange": "NFO",
            "tradingsymbol": "NIFTY2592925000CE",
            "transaction_type": "SELL",
            "variety": "regular",
            "product": "NRML",
            "order_type": "SL-M",
            "quantity": 75,
            "price": 0,
            "trigger_price": 95.5,
        }
    ]


def test_session_error_maps_to_broker_session_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, httpx.Response(403, json={"error_type": "TokenException"}))

    with pytest.raises(BrokerSessionError, match="reconnect"):
        fetch_margin("key", "token", [_order(Side.BUY)])
