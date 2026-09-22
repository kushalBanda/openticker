from dataclasses import replace
from datetime import date

import pytest

from openticker.core.options.underlyings import underlying_of
from openticker.core.orders.settlement import settlement_price, settles_at
from openticker.ports.models import EXCHANGE_TIMEZONE, Exchange, Instrument, InstrumentType
from tests.fixtures.calendar import NO_HOLIDAYS
from tests.fixtures.options import option

EXPIRY = date(2026, 9, 22)
CALL = option("NIFTY", EXPIRY, 23400, InstrumentType.CE)
PUT = option("NIFTY", EXPIRY, 23400, InstrumentType.PE)


@pytest.mark.parametrize(
    ("contract", "close", "price"),
    [
        (CALL, 23450.5, 50.5),
        (CALL, 23300.0, 0.0),
        (PUT, 23300.0, 100.0),
        (PUT, 23500.0, 0.0),
        (replace(CALL, strike=23000.0), 23118.6, 118.6),  # float subtraction gives 118.5999...
    ],
)
def test_options_settle_at_intrinsic_value(
    contract: Instrument, close: float, price: float
) -> None:
    assert settlement_price(contract, close) == price


def test_futures_settle_at_the_underlying_close() -> None:
    future = replace(
        CALL, symbol="NIFTY22SEP26FUT", instrument_type=InstrumentType.FUT, strike=None
    )

    assert settlement_price(future, 23411.2) == 23411.2


def test_settlement_waits_for_the_close_to_be_final() -> None:
    at = settles_at(CALL, EXPIRY, NO_HOLIDAYS).astimezone(EXCHANGE_TIMEZONE)

    assert (at.date(), at.hour, at.minute) == (EXPIRY, 15, 45)


@pytest.mark.parametrize(
    ("symbol", "exchange", "expected"),
    [
        ("NIFTY22SEP2623400CE", Exchange.NFO, ("NIFTY 50", Exchange.NSE)),
        ("BANKNIFTY29SEP26FUT", Exchange.NFO, ("NIFTY BANK", Exchange.NSE)),
        ("NIFTYNXT5029SEP2670000PE", Exchange.NFO, ("NIFTY NEXT 50", Exchange.NSE)),
        ("SENSEX24SEP2680000CE", Exchange.BFO, ("SENSEX", Exchange.BSE)),
        ("RELIANCE29SEP261300CE", Exchange.NFO, ("RELIANCE", Exchange.NSE)),
        ("M&M29SEP26FUT", Exchange.NFO, ("M&M", Exchange.NSE)),
        ("GOLD05OCT26FUT", Exchange.MCX, None),
    ],
)
def test_underlying_is_read_from_the_contract_symbol(
    symbol: str, exchange: Exchange, expected: tuple[str, Exchange] | None
) -> None:
    day = int(symbol.split("SEP")[0][-2:]) if "SEP" in symbol else 5
    month = 9 if "SEP" in symbol else 10
    contract = replace(CALL, symbol=symbol, exchange=exchange, expiry=date(2026, month, day))

    assert underlying_of(contract) == expected
