"""Log in to a broker, or log out (ADR 5 and ADR 33 in docs/adr). The session
is stored encrypted and never returned."""

from openticker.events.bus import EventPublisher
from openticker.events.types import BrokerConnected, BrokerDisconnected
from openticker.ports.broker_port import BrokerPort
from openticker.ports.models import Credentials
from openticker.storage.sqlite.credentials_repo import delete_credentials, save_credentials


def connect_broker(
    broker: BrokerPort, request_token: str, events: EventPublisher, triggered_by: str
) -> Credentials:
    credentials = broker.authenticate(request_token)
    save_credentials(credentials)
    events.publish(BrokerConnected(broker=credentials.broker, triggered_by=triggered_by))
    return credentials


def disconnect_broker(broker: str, events: EventPublisher, triggered_by: str) -> bool:
    """Deletes the stored session; False when there was none."""
    if not delete_credentials(broker):
        return False
    events.publish(BrokerDisconnected(broker=broker, triggered_by=triggered_by))
    return True
