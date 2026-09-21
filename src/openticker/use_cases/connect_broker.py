"""OAuth + credential storage (ADR 5 in docs/adr)."""

from openticker.ports.broker_port import BrokerPort
from openticker.ports.models import Credentials
from openticker.storage.sqlite.credentials_repo import save_credentials


def connect_broker(broker: BrokerPort, request_token: str) -> Credentials:
    credentials = broker.authenticate(request_token)
    save_credentials(credentials)
    return credentials
