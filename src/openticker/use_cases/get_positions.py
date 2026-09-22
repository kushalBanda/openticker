"""Net positions from the order adapter, valued at current prices."""

from openticker.ports.broker_port import BrokerPort
from openticker.ports.models import Position


def get_positions(broker: BrokerPort) -> list[Position]:
    return broker.get_positions()
