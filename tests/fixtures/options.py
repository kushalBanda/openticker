"""Option and index instruments for chain tests, named the way sync names them (ADR 4)."""

from datetime import date

from openticker.ports.models import Exchange, Instrument, InstrumentType

NIFTY_INDEX = Instrument(
    symbol="NIFTY 50",
    broker_symbol="NIFTY 50",
    exchange=Exchange.NSE,
    broker_exchange="NSE",
    token="256265",
    expiry=None,
    strike=None,
    lot_size=0,
    instrument_type=InstrumentType.INDEX,
    tick_size=0.0,
)


def option(
    name: str,
    expiry: date,
    strike: float,
    option_type: InstrumentType,
    exchange: Exchange = Exchange.NFO,
) -> Instrument:
    strike_text = str(int(strike)) if strike.is_integer() else str(strike)
    symbol = f"{name}{expiry.strftime('%d%b%y').upper()}{strike_text}{option_type.value}"
    return Instrument(
        symbol=symbol,
        broker_symbol=symbol,
        exchange=exchange,
        broker_exchange=exchange.value,
        token=f"token-{symbol}",
        expiry=expiry,
        strike=strike,
        lot_size=65,
        instrument_type=option_type,
        tick_size=0.05,
    )


def chain_contracts(
    name: str, expiry: date, strikes: list[float], exchange: Exchange = Exchange.NFO
) -> list[Instrument]:
    return [
        option(name, expiry, strike, option_type, exchange)
        for strike in strikes
        for option_type in (InstrumentType.CE, InstrumentType.PE)
    ]
