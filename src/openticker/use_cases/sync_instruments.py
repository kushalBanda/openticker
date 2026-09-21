"""BrokerPort.get_instrument_master -> storage upsert -> InstrumentSyncCompleted."""

from openticker.events.bus import EventPublisher
from openticker.events.types import InstrumentSyncCompleted
from openticker.ports.broker_port import BrokerPort
from openticker.storage.sqlite.instruments_repo import upsert_instruments


def sync_instruments(broker_name: str, broker: BrokerPort, events: EventPublisher) -> int:
    count = upsert_instruments(broker.get_instrument_master())
    events.publish(InstrumentSyncCompleted(broker=broker_name, count=count))
    return count
