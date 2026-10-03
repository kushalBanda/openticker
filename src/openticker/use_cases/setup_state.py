"""The web app's first-run checklist (ADR 34 in docs/adr), read from what
already exists: nothing is stored for it."""

from dataclasses import dataclass
from datetime import datetime

from openticker.ports.models import EXCHANGE_TIMEZONE
from openticker.storage.sqlite.agent_clients_repo import list_clients
from openticker.storage.sqlite.pnl_repo import first_fill_at
from openticker.use_cases.settings_state import broker_session, instrument_status


@dataclass(frozen=True)
class SetupState:
    broker_connected: bool
    instruments_synced_today: bool
    instrument_count: int
    agent_seen: str | None  # the first MCP client seen, by name
    first_fill_at: datetime | None

    @property
    def done(self) -> bool:
        return (
            self.broker_connected
            and self.instrument_count > 0
            and self.agent_seen is not None
            and self.first_fill_at is not None
        )


def setup_state(broker: str, now: datetime) -> SetupState:
    instruments = instrument_status()
    synced = instruments.synced_at
    today = now.astimezone(EXCHANGE_TIMEZONE).date()
    clients = sorted(list_clients(), key=lambda client: client.first_seen_at)
    return SetupState(
        broker_connected=broker_session(broker, now).connected,
        instruments_synced_today=synced is not None
        and synced.astimezone(EXCHANGE_TIMEZONE).date() == today,
        instrument_count=sum(instruments.counts.values()),
        agent_seen=clients[0].name if clients else None,
        first_fill_at=first_fill_at(),
    )
