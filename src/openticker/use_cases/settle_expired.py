"""Settles positions in expired futures and options (ADR 11 in docs/adr).

Once an expiry day's close is final, every position still open in a contract
that expired then is closed at its settlement price: derived from the
underlying's close on expiry day for NSE and BSE derivatives, or the
contract's own close on expiry day where there is no listed underlying (MCX).
Closes are read from daily candles, so a daemon that was down on expiry day
settles correctly when it next runs.
"""

from dataclasses import dataclass
from datetime import date, datetime

from openticker.core.calendar.models import MarketCalendar
from openticker.core.options.underlyings import underlying_of
from openticker.core.orders.models import OrderStatus
from openticker.core.orders.settlement import settlement_price, settles_at
from openticker.events.bus import EventPublisher
from openticker.events.types import PositionSettled
from openticker.ports.broker_port import BrokerPort
from openticker.ports.errors import BrokerError
from openticker.ports.models import Instrument, Interval
from openticker.ports.sandbox_port import SandboxPort
from openticker.use_cases.resolve_instrument import UnknownInstrumentError, resolve_instrument


@dataclass(frozen=True)
class SettlementRun:
    settled: list[PositionSettled]
    waiting: list[str]  # positions due but not yet priceable, and why


def settle_expired_positions(
    broker: BrokerPort,
    sandbox: SandboxPort,
    events: EventPublisher,
    calendar: MarketCalendar,
    now: datetime,
) -> SettlementRun:
    run = SettlementRun(settled=[], waiting=[])
    closes: dict[tuple[str, date], float] = {}
    for position in sandbox.open_positions():
        expiry = position.instrument.expiry
        if expiry is None or now < settles_at(position.instrument, expiry, calendar):
            continue
        try:
            price, detail = _price(broker, position.instrument, expiry, closes)
        except (BrokerError, UnknownInstrumentError, LookupError) as exc:
            run.waiting.append(f"{position.instrument.symbol}: {exc}")
            continue
        result = sandbox.settle_position(
            position.instrument, position.product, price, f"settled at expiry: {detail}", now
        )
        if result.status is not OrderStatus.FILLED:
            continue
        event = PositionSettled(
            symbol=position.instrument.symbol,
            product=position.product.value,
            quantity=position.quantity,
            price=price,
            realized_pnl=round((price - position.average_price) * position.quantity, 2),
            detail=detail,
        )
        events.publish(event)
        run.settled.append(event)
    return run


def _price(
    broker: BrokerPort,
    contract: Instrument,
    expiry: date,
    closes: dict[tuple[str, date], float],
) -> tuple[float, str]:
    underlying = underlying_of(contract)
    if underlying is None:
        close = _close(broker, contract, expiry, closes)
        return close, f"{contract.symbol} closed at {close:,.2f} on {expiry}"
    symbol, exchange = underlying
    close = _close(broker, resolve_instrument(symbol, exchange.value), expiry, closes)
    price = settlement_price(contract, close)
    return price, f"{symbol} closed at {close:,.2f} on {expiry}"


def _close(
    broker: BrokerPort, instrument: Instrument, day: date, closes: dict[tuple[str, date], float]
) -> float:
    key = (f"{instrument.exchange}:{instrument.symbol}", day)
    if key not in closes:
        bars = broker.get_historical_bars(instrument, Interval.DAY.value, day, day)
        if not bars:
            raise LookupError(f"no {day} close for {instrument.symbol} yet")
        closes[key] = bars[-1].close
    return closes[key]
