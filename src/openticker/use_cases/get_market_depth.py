"""Instrument resolution + BrokerPort.get_market_depth passthrough."""

from openticker.ports.broker_port import BrokerPort
from openticker.ports.models import MarketDepth
from openticker.use_cases.resolve_instrument import resolve_instrument


def get_market_depth(broker: BrokerPort, symbol: str, exchange: str) -> MarketDepth:
    return broker.get_market_depth(resolve_instrument(symbol, exchange))
