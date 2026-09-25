"""The expected figures are Kite's own virtual contract note (POST
/charges/orders) for the same orders, fetched on 2026-09-25: the shipped
rates reproduce Zerodha's charges to the paisa."""

import json
from dataclasses import replace
from datetime import date
from importlib.resources import files

import pytest

from openticker.core.orders.charges import (
    Basis,
    Charge,
    ChargeBook,
    ChargeBookError,
    Segment,
    charges_for,
    parse_charge_book,
    segment_of,
)
from openticker.ports.models import Exchange, InstrumentType, Product, Side
from tests.fixtures.fake_broker import FAKE_INSTRUMENT

SHIPPED = json.loads(files("openticker").joinpath("data/charges.json").read_text())
BOOK = parse_charge_book(SHIPPED)
NIFTY_CE = replace(
    FAKE_INSTRUMENT,
    symbol="NIFTY29SEP2623200CE",
    exchange=Exchange.NFO,
    instrument_type=InstrumentType.CE,
    lot_size=65,
    expiry=date(2026, 9, 29),
    strike=23200.0,
)
NIFTY_FUT = replace(NIFTY_CE, symbol="NIFTY29SEP26FUT", instrument_type=InstrumentType.FUT)
SENSEX_FUT = replace(NIFTY_FUT, symbol="SENSEX29OCT26FUT", exchange=Exchange.BFO)
CRUDE_FUT = replace(NIFTY_FUT, symbol="CRUDEOIL19OCT26FUT", exchange=Exchange.MCX)


def _total(instrument: object, product: Product, side: Side, quantity: int, price: float) -> float:
    schedule = BOOK.for_fill(instrument, product)  # type: ignore[arg-type]
    assert schedule is not None
    return charges_for(schedule, side, quantity, price).total


@pytest.mark.parametrize(
    ("instrument", "product", "side", "quantity", "price", "kite"),
    [
        (FAKE_INSTRUMENT, Product.CNC, Side.BUY, 10, 1226.0, 14.72),
        (FAKE_INSTRUMENT, Product.CNC, Side.SELL, 10, 1226.0, 12.72),
        (FAKE_INSTRUMENT, Product.MIS, Side.BUY, 10, 1226.0, 4.80),
        (FAKE_INSTRUMENT, Product.MIS, Side.SELL, 10, 1226.0, 7.86),
        (NIFTY_FUT, Product.NRML, Side.BUY, 65, 23181.5, 87.92),
        (NIFTY_FUT, Product.NRML, Side.SELL, 65, 23181.5, 811.31),
        (NIFTY_CE, Product.NRML, Side.BUY, 65, 86.7, 25.97),
        (NIFTY_CE, Product.NRML, Side.SELL, 65, 86.7, 34.42),
        (SENSEX_FUT, Product.NRML, Side.BUY, 20, 74610.0, 55.36),
        (SENSEX_FUT, Product.NRML, Side.SELL, 20, 74610.0, 771.46),
    ],
)
def test_the_shipped_rates_reproduce_kites_contract_note(
    instrument: object, product: Product, side: Side, quantity: int, price: float, kite: float
) -> None:
    assert _total(instrument, product, side, quantity, price) == pytest.approx(kite, abs=0.011)


def test_options_sell_pays_stt_on_premium_and_the_buy_pays_none() -> None:
    schedule = BOOK.for_fill(NIFTY_CE, Product.NRML)
    assert schedule is not None

    sold = charges_for(schedule, Side.SELL, 65, 100.0).items
    bought = charges_for(schedule, Side.BUY, 65, 100.0).items

    assert sold["transaction_tax"] == pytest.approx(65 * 100.0 * 0.0015, abs=0.01)
    assert bought["transaction_tax"] == 0.0


def test_intraday_brokerage_is_capped_at_20_per_order() -> None:
    schedule = BOOK.for_fill(FAKE_INSTRUMENT, Product.MIS)
    assert schedule is not None

    assert charges_for(schedule, Side.BUY, 1000, 2500.0).items["brokerage"] == 20.0
    assert charges_for(schedule, Side.BUY, 1, 2500.0).items["brokerage"] == 0.75


def test_delivery_has_no_brokerage() -> None:
    schedule = BOOK.for_fill(FAKE_INSTRUMENT, Product.CNC)
    assert schedule is not None

    assert "brokerage" not in charges_for(schedule, Side.BUY, 10, 1000.0).items


def test_gst_is_on_brokerage_exchange_and_sebi_fees_only() -> None:
    schedule = BOOK.for_fill(NIFTY_CE, Product.NRML)
    assert schedule is not None

    items = charges_for(schedule, Side.SELL, 65, 100.0).items

    taxed = items["brokerage"] + items["exchange_txn"] + items["sebi"]
    assert items["gst"] == pytest.approx(taxed * 0.18, abs=0.01)


def test_stamp_duty_is_on_the_buy_side_rounded_to_the_rupee() -> None:
    schedule = BOOK.for_fill(NIFTY_FUT, Product.NRML)
    assert schedule is not None

    assert charges_for(schedule, Side.BUY, 65, 23186.0).items["stamp_duty"] == 30.0  # 30.14
    assert charges_for(schedule, Side.SELL, 65, 23186.0).items["stamp_duty"] == 0.0


def test_bse_futures_have_no_exchange_charge() -> None:
    schedule = BOOK.for_fill(SENSEX_FUT, Product.NRML)
    assert schedule is not None

    assert charges_for(schedule, Side.BUY, 20, 74610.0).items["exchange_txn"] == 0.0


def test_the_shipped_book_covers_nse_and_bse_but_not_mcx() -> None:
    covered = set(BOOK.schedules)

    assert covered == {
        (segment, exchange)
        for segment, exchanges in (
            (Segment.EQUITY_DELIVERY, (Exchange.NSE, Exchange.BSE)),
            (Segment.EQUITY_INTRADAY, (Exchange.NSE, Exchange.BSE)),
            (Segment.FUTURES, (Exchange.NFO, Exchange.BFO)),
            (Segment.OPTIONS, (Exchange.NFO, Exchange.BFO)),
        )
        for exchange in exchanges
    }
    assert BOOK.for_fill(CRUDE_FUT, Product.NRML) is None  # no contract multiplier yet


def test_segment_follows_the_instrument_and_product() -> None:
    assert segment_of(FAKE_INSTRUMENT, Product.CNC) is Segment.EQUITY_DELIVERY
    assert segment_of(FAKE_INSTRUMENT, Product.MIS) is Segment.EQUITY_INTRADAY
    assert segment_of(NIFTY_CE, Product.MIS) is Segment.OPTIONS
    assert segment_of(CRUDE_FUT, Product.NRML) is Segment.COMMODITY_FUTURES


def test_a_capped_order_charge_takes_the_smaller() -> None:
    capped = Charge("brokerage", Basis.ORDER, rate=0.0003, cap=20.0)

    assert capped.amount(Side.BUY, 1_000_000.0) == 20.0
    assert capped.amount(Side.BUY, 10_000.0) == pytest.approx(3.0)


def test_a_bad_entry_is_named() -> None:
    broken = json.loads(json.dumps(SHIPPED))
    broken["schedules"][2]["charges"][0]["basis"] = "monthly"

    with pytest.raises(ChargeBookError, match=r"schedules\[2\]"):
        parse_charge_book(broken)


def test_a_rate_of_one_or_more_is_refused() -> None:
    broken = json.loads(json.dumps(SHIPPED))
    broken["schedules"][0]["charges"][0]["rate"] = 1.5

    with pytest.raises(ChargeBookError, match="fraction"):
        parse_charge_book(broken)


def test_a_segment_listed_twice_is_refused() -> None:
    doubled = json.loads(json.dumps(SHIPPED))
    doubled["schedules"].append(doubled["schedules"][0])

    with pytest.raises(ChargeBookError, match="listed twice"):
        parse_charge_book(doubled)


def test_an_empty_book_charges_nothing() -> None:
    assert ChargeBook({}).for_fill(FAKE_INSTRUMENT, Product.MIS) is None
