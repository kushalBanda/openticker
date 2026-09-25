from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from openticker.core.orders.models import OrderRequest, OrderType
from openticker.ports.models import Exchange, MarginRequirement, Product, Side
from openticker.storage.sqlite.instruments_repo import upsert_instruments
from openticker.use_cases.errors import BatchTooLargeError
from openticker.use_cases.get_margin import (
    MAX_MARGIN_ORDERS,
    InvalidMarginOrderError,
    get_margin,
)
from openticker.use_cases.place_basket import BasketOrder
from openticker.use_cases.resolve_instrument import UnknownInstrumentError
from tests.fixtures.fake_broker import FAKE_INSTRUMENT, FakeBrokerPort

CLOSED = datetime(2026, 9, 26, 6, 0, tzinfo=UTC)  # Saturday: margin needs no open market


class _Recording(FakeBrokerPort):
    def __init__(self) -> None:
        self.asked: list[list[OrderRequest]] = []

    def get_margin(self, orders: Sequence[OrderRequest]) -> MarginRequirement:
        self.asked.append(list(orders))
        return super().get_margin(orders)


@pytest.fixture(autouse=True)
def _master() -> None:
    upsert_instruments([FAKE_INSTRUMENT])


def _order(side: Side, **fields: object) -> BasketOrder:
    base: dict[str, object] = {
        "symbol": "RELIANCE",
        "exchange": Exchange.NSE,
        "side": side,
        "quantity": 1,
        "product": Product.MIS,
    }
    return BasketOrder(**{**base, **fields})  # type: ignore[arg-type]


def test_passes_orders_to_broker_in_caller_order() -> None:
    broker = _Recording()

    margin = get_margin(broker, [_order(Side.SELL), _order(Side.BUY, quantity=2)], CLOSED)

    [asked] = broker.asked
    assert [(r.side, r.quantity) for r in asked] == [(Side.SELL, 1), (Side.BUY, 2)]
    assert margin.benefit == 1000.0


def test_invalid_order_names_its_index_and_nothing_is_priced() -> None:
    broker = _Recording()

    with pytest.raises(InvalidMarginOrderError, match=r"order 2 \(RELIANCE\): LIMIT orders need"):
        get_margin(broker, [_order(Side.BUY), _order(Side.BUY, order_type=OrderType.LIMIT)], CLOSED)
    with pytest.raises(UnknownInstrumentError, match="order 1: no instrument 'NOPE'"):
        get_margin(broker, [_order(Side.BUY, symbol="NOPE")], CLOSED)
    with pytest.raises(BatchTooLargeError):
        get_margin(broker, [_order(Side.BUY)] * (MAX_MARGIN_ORDERS + 1), CLOSED)

    assert broker.asked == []
