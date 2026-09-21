from datetime import date

import httpx
import pytest

from openticker.adapters.brokers.zerodha import instruments
from openticker.ports.models import Exchange, Instrument, InstrumentType

_HEADER = (
    "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,"
    "tick_size,lot_size,instrument_type,segment,exchange\n"
)

# Rows in Kite's CSV shape, one per case the parser has to handle (first four copied
# from the real 2026-09-21 download; the fractional-strike and CDS rows are synthetic).
_CSV = _HEADER + (
    '738561,2885,RELIANCE,"RELIANCE INDUSTRIES",0,,0,0.05,1,EQ,NSE,NSE\n'
    '256265,1001,NIFTY 50,"NIFTY 50",0,,0,0,0,EQ,INDICES,NSE\n'
    '13238786,51714,NIFTY26SEPFUT,"NIFTY",0,2026-09-29,0,0.1,65,FUT,NFO-FUT,NFO\n'
    '10967554,42842,NIFTY2692223350CE,"NIFTY",0,2026-09-22,23350,0.05,65,CE,NFO-OPT,NFO\n'
    '12345678,48225,IDEA26SEP8.5PE,"IDEA",0,2026-09-29,8.5,0.05,71475,PE,NFO-OPT,NFO\n'
    '1234,5,USDINR26SEPFUT,"USDINR",0,2026-09-26,0,0.0025,1,FUT,CDS-FUT,CDS\n'
)


def _by_broker_symbol(csv_text: str) -> dict[str, Instrument]:
    return {row.broker_symbol: row for row in instruments.parse_instrument_csv(csv_text)}


def test_parse_drops_unsupported_exchanges() -> None:
    parsed = _by_broker_symbol(_CSV)

    assert "USDINR26SEPFUT" not in parsed
    assert len(parsed) == 5


def test_parse_equity_keeps_broker_symbol() -> None:
    reliance = _by_broker_symbol(_CSV)["RELIANCE"]

    assert reliance.symbol == "RELIANCE"
    assert reliance.exchange is Exchange.NSE
    assert reliance.instrument_type is InstrumentType.EQ
    assert reliance.token == "738561"
    assert reliance.expiry is None
    assert reliance.strike is None


def test_parse_indices_segment_becomes_index_type() -> None:
    nifty = _by_broker_symbol(_CSV)["NIFTY 50"]

    assert nifty.instrument_type is InstrumentType.INDEX
    assert nifty.symbol == "NIFTY 50"


def test_parse_future_gets_standardized_symbol() -> None:
    future = _by_broker_symbol(_CSV)["NIFTY26SEPFUT"]

    assert future.symbol == "NIFTY29SEP26FUT"
    assert future.expiry == date(2026, 9, 29)
    assert future.strike is None
    assert future.lot_size == 65


def test_parse_weekly_option_gets_standardized_symbol() -> None:
    option = _by_broker_symbol(_CSV)["NIFTY2692223350CE"]

    assert option.symbol == "NIFTY22SEP2623350CE"
    assert option.strike == 23350.0
    assert option.instrument_type is InstrumentType.CE


def test_parse_fractional_strike_keeps_decimal() -> None:
    option = _by_broker_symbol(_CSV)["IDEA26SEP8.5PE"]

    assert option.symbol == "IDEA29SEP268.5PE"


def test_parse_raises_when_nothing_usable() -> None:
    with pytest.raises(instruments.KiteInstrumentsError):
        instruments.parse_instrument_csv(_HEADER)


def test_download_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        httpx, "get", lambda url, timeout: httpx.Response(503, text="unavailable")
    )

    with pytest.raises(instruments.KiteInstrumentsError):
        instruments.download_instrument_csv()
