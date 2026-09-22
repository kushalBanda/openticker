"""Capital, margin in use and realized P&L from the order adapter."""

from openticker.ports.broker_port import BrokerPort
from openticker.ports.models import Funds


def get_funds(broker: BrokerPort) -> Funds:
    return broker.get_funds()
