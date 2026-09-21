"""Downloads and normalizes Kite's public instrument CSV into `Instrument` rows.

The CSV (`https://api.kite.trade/instruments`, no auth) covers every segment
Kite trades. Only the exchanges `ports.models.Exchange` knows are kept; CDS,
NCO, NSEIX and GLOBAL rows are dropped.

Standardized symbols — what `Instrument.symbol` holds, broker-independent:
  equity / index   the broker's own tradingsymbol (RELIANCE, NIFTY 50)
  future           <name><DDMMMYY>FUT              (NIFTY24SEP26FUT)
  option           <name><DDMMMYY><strike><CE|PE>  (NIFTY22SEP2623350CE)
Kite's own derivative symbols differ between weekly and monthly expiries
(NIFTY2692223350CE vs. NIFTY26SEP23350CE); the standardized form doesn't.
"""

import csv
import io
from datetime import date
from http import HTTPStatus

import httpx

from openticker.ports.errors import BrokerError
from openticker.ports.models import Exchange, Instrument, InstrumentType

KITE_INSTRUMENTS_URL = "https://api.kite.trade/instruments"

_SUPPORTED_EXCHANGES = {exchange.value for exchange in Exchange}
_DERIVATIVE_TYPES = {InstrumentType.FUT, InstrumentType.CE, InstrumentType.PE}


class KiteInstrumentsError(BrokerError):
    """The instrument CSV couldn't be downloaded or didn't parse into anything usable."""


def download_instrument_csv() -> str:
    response = httpx.get(KITE_INSTRUMENTS_URL, timeout=60.0)
    if response.status_code >= HTTPStatus.BAD_REQUEST:
        raise KiteInstrumentsError(
            f"instrument CSV download failed: HTTP {response.status_code}"
        )
    return response.text


def parse_instrument_csv(csv_text: str) -> list[Instrument]:
    instruments = [
        _to_instrument(row)
        for row in csv.DictReader(io.StringIO(csv_text))
        if row["exchange"] in _SUPPORTED_EXCHANGES
    ]
    if not instruments:
        # An empty or truncated download must not look like a successful sync of zero rows.
        raise KiteInstrumentsError("instrument CSV contained no rows for any supported exchange")
    return instruments


def _to_instrument(row: dict[str, str]) -> Instrument:
    instrument_type = (
        InstrumentType.INDEX if row["segment"] == "INDICES" else InstrumentType(row["instrument_type"])
    )
    expiry = date.fromisoformat(row["expiry"]) if row["expiry"] else None
    strike = float(row["strike"]) if instrument_type in (InstrumentType.CE, InstrumentType.PE) else None
    return Instrument(
        symbol=_standard_symbol(row, instrument_type, expiry, strike),
        broker_symbol=row["tradingsymbol"],
        exchange=Exchange(row["exchange"]),
        broker_exchange=row["exchange"],
        token=row["instrument_token"],
        expiry=expiry,
        strike=strike,
        lot_size=int(row["lot_size"]),
        instrument_type=instrument_type,
        tick_size=float(row["tick_size"]),
    )


def _standard_symbol(
    row: dict[str, str],
    instrument_type: InstrumentType,
    expiry: date | None,
    strike: float | None,
) -> str:
    if instrument_type not in _DERIVATIVE_TYPES:
        return row["tradingsymbol"]
    if expiry is None:
        raise KiteInstrumentsError(f"derivative {row['tradingsymbol']!r} has no expiry")
    base = row["name"].replace(" ", "") + expiry.strftime("%d%b%y").upper()
    if instrument_type is InstrumentType.FUT:
        return f"{base}FUT"
    if strike is None:
        raise KiteInstrumentsError(f"option {row['tradingsymbol']!r} has no strike")
    strike_text = str(int(strike)) if strike.is_integer() else str(strike)
    return f"{base}{strike_text}{instrument_type.value}"
