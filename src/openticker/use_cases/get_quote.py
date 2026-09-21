"""Instrument resolution + BrokerPort.get_quote passthrough."""

from openticker.ports.broker_port import BrokerPort
from openticker.ports.models import Quote
from openticker.use_cases.resolve_instrument import resolve_instrument


def get_quote(broker: BrokerPort, symbol: str, exchange: str) -> Quote:
    return broker.get_quote(resolve_instrument(symbol, exchange))
