from dataclasses import replace

from openticker.core.orders.charge_check import (
    ChargeDifference,
    ChargeSample,
    broker_requests,
    differences,
)
from openticker.core.orders.charges import Charges
from openticker.ports.models import Exchange, Instrument, InstrumentType, Product, Side
from tests.fixtures.fake_broker import FAKE_INSTRUMENT

OURS = Charges({"brokerage": 20.0, "transaction_tax": 8.45, "gst": 3.6})

FUTURE = replace(
    FAKE_INSTRUMENT,
    symbol="NIFTY29SEP26FUT",
    exchange=Exchange.NFO,
    instrument_type=InstrumentType.FUT,
    lot_size=65,
)
BSE_EQUITY = replace(FAKE_INSTRUMENT, exchange=Exchange.BSE)


def _sample(
    side: Side, product: Product = Product.CNC, instrument: Instrument = FAKE_INSTRUMENT
) -> ChargeSample:
    return ChargeSample(instrument, side, 10, product, 1000.0)


def test_equal_charges_differ_in_nothing() -> None:
    assert differences(OURS, Charges(dict(OURS.items))) == ()


def test_a_paisa_of_rounding_is_not_a_difference() -> None:
    assert differences(OURS, Charges({**OURS.items, "transaction_tax": 8.46})) == ()


def test_a_differing_item_and_the_total_carry_both_figures() -> None:
    broker = Charges({**OURS.items, "transaction_tax": 10.0})

    assert differences(OURS, broker) == (
        ChargeDifference("transaction_tax", 8.45, 10.0),
        ChargeDifference("total", 32.05, 33.6),
    )


def test_an_item_only_the_broker_charges_counts_against_zero() -> None:
    broker = Charges({**OURS.items, "ipft": 0.5})

    assert differences(OURS, broker) == (
        ChargeDifference("ipft", 0.0, 0.5),
        ChargeDifference("total", 32.05, 32.55),
    )


def test_intraday_goes_as_a_pair_and_nothing_else_can_net() -> None:
    delivery_buy, delivery_sell = _sample(Side.BUY), _sample(Side.SELL)
    future_buy = _sample(Side.BUY, Product.NRML, FUTURE)
    future_sell = _sample(Side.SELL, Product.NRML, FUTURE)
    nse_mis = (_sample(Side.BUY, Product.MIS), _sample(Side.SELL, Product.MIS))
    bse_mis = (
        _sample(Side.BUY, Product.MIS, BSE_EQUITY),
        _sample(Side.SELL, Product.MIS, BSE_EQUITY),
    )

    requests = broker_requests(
        [delivery_buy, delivery_sell, *nse_mis, future_buy, future_sell, *bse_mis]
    )

    # Delivery and futures never share a request with their own other side.
    assert requests == [(delivery_buy, future_buy), (delivery_sell, future_sell), nse_mis, bse_mis]
