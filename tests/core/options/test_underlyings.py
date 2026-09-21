from dataclasses import replace

import pytest

from openticker.core.options.underlyings import UnsupportedUnderlyingError, options_of
from openticker.ports.models import Exchange, InstrumentType
from tests.fixtures.fake_broker import FAKE_INSTRUMENT
from tests.fixtures.options import NIFTY_INDEX


def test_index_maps_to_its_option_name() -> None:
    assert options_of(NIFTY_INDEX) == ("NIFTY", Exchange.NFO)
    assert options_of(replace(NIFTY_INDEX, symbol="SENSEX", exchange=Exchange.BSE)) == (
        "SENSEX",
        Exchange.BFO,
    )


def test_stock_options_use_the_stock_symbol() -> None:
    assert options_of(FAKE_INSTRUMENT) == ("RELIANCE", Exchange.NFO)


def test_index_without_options_names_the_supported_ones() -> None:
    with pytest.raises(UnsupportedUnderlyingError, match="NIFTY BANK"):
        options_of(replace(NIFTY_INDEX, symbol="NIFTY IT"))


def test_a_future_is_not_an_underlying() -> None:
    future = replace(FAKE_INSTRUMENT, exchange=Exchange.NFO, instrument_type=InstrumentType.FUT)

    with pytest.raises(UnsupportedUnderlyingError):
        options_of(future)
