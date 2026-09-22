from dataclasses import replace
from datetime import date

import pytest

from openticker.core.orders.models import OrderRequest, OrderType
from openticker.core.orders.validation import validate_order
from openticker.ports.models import InstrumentType, Product, Side
from tests.fixtures.fake_broker import FAKE_INSTRUMENT
from tests.fixtures.options import NIFTY_INDEX, option

TODAY = date(2026, 9, 22)
NIFTY_CALL = option("NIFTY", TODAY, 25000, InstrumentType.CE)  # lot size 65


def _request(**changes: object) -> OrderRequest:
    base = OrderRequest(
        instrument=FAKE_INSTRUMENT,
        side=Side.BUY,
        quantity=10,
        product=Product.CNC,
        order_type=OrderType.MARKET,
        price=None,
        triggered_by="test",
    )
    return replace(base, **changes)  # type: ignore[arg-type]


def test_a_well_formed_order_is_valid() -> None:
    assert validate_order(_request(), TODAY).valid
    assert validate_order(
        _request(instrument=NIFTY_CALL, quantity=130, product=Product.NRML), TODAY
    ).valid  # expiry day itself is still tradeable


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"instrument": NIFTY_INDEX}, "index"),
        ({"instrument": replace(NIFTY_CALL, expiry=date(2026, 9, 21))}, "expired"),
        ({"instrument": NIFTY_CALL, "quantity": 100, "product": Product.NRML}, "lot size 65"),
        ({"product": Product.NRML}, "CNC or MIS"),
        ({"instrument": NIFTY_CALL, "quantity": 65, "product": Product.CNC}, "NRML or MIS"),
        ({"price": 99.0}, "take no price"),
        ({"order_type": OrderType.LIMIT}, "LIMIT orders need a price"),
        ({"order_type": OrderType.LIMIT, "price": 99.0, "trigger_price": 98.0}, "no trigger"),
        ({"order_type": OrderType.SL_M}, "need a trigger_price"),
        ({"order_type": OrderType.SL_M, "trigger_price": 99.0, "price": 99.5}, "take no price"),
        ({"order_type": OrderType.SL, "trigger_price": 99.0}, "SL orders need a price"),
        ({"order_type": OrderType.LIMIT, "price": 99.03}, "tick size 0.05"),
        ({"order_type": OrderType.LIMIT, "price": -5.0}, "positive"),
        (
            {"order_type": OrderType.SL, "price": 99.0, "trigger_price": 100.0},
            "at or above its trigger",
        ),
        (
            {"order_type": OrderType.SL, "side": Side.SELL, "price": 101.0, "trigger_price": 100.0},
            "at or below its trigger",
        ),
        ({"quantity": 0}, "positive"),
    ],
)
def test_malformed_orders_say_why(changes: dict[str, object], reason: str) -> None:
    result = validate_order(_request(**changes), TODAY)

    assert not result.valid
    assert result.reason is not None and reason in result.reason


@pytest.mark.parametrize(
    "changes",
    [
        {"order_type": OrderType.LIMIT, "price": 99.05},
        {"order_type": OrderType.SL_M, "trigger_price": 101.0},
        {"order_type": OrderType.SL, "price": 101.5, "trigger_price": 101.0},
        {"order_type": OrderType.SL, "side": Side.SELL, "price": 98.5, "trigger_price": 99.0},
    ],
)
def test_resting_order_types_take_their_prices(changes: dict[str, object]) -> None:
    assert validate_order(_request(**changes), TODAY).valid
