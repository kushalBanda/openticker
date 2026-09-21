"""BrokerPort.get_instrument_master -> storage upsert."""

from openticker.ports.broker_port import BrokerPort
from openticker.storage.sqlite.instruments_repo import upsert_instruments


def sync_instruments(broker: BrokerPort) -> int:
    return upsert_instruments(broker.get_instrument_master())
