"""BrokerPort.get_historical_bars -> DuckDB write -> return.

Always fetches from the broker; DuckDB is the durable copy for later bulk
reads (`bars_repo.get_bars`), not a cache consulted first.
"""

from datetime import date

from openticker.ports.broker_port import BrokerPort
from openticker.ports.models import Bar
from openticker.storage.duckdb.bars_repo import write_bars
from openticker.use_cases.resolve_instrument import resolve_instrument


def get_historical_bars(
    broker: BrokerPort, symbol: str, exchange: str, interval: str, start: date, end: date
) -> list[Bar]:
    bars = broker.get_historical_bars(resolve_instrument(symbol, exchange), interval, start, end)
    write_bars(bars)
    return bars
