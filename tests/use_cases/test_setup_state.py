from datetime import UTC, datetime

from openticker.events.subscribers.audit_log import record_event
from openticker.events.types import InstrumentSyncCompleted
from openticker.ports.models import Credentials, Side
from openticker.storage.sqlite.agent_clients_repo import note_client
from openticker.storage.sqlite.credentials_repo import save_credentials
from openticker.use_cases.setup_state import setup_state
from tests.fixtures.pnl_desk import new_desk

NOW = datetime(2026, 9, 21, 4, 30, tzinfo=UTC)  # Monday 10:00 IST


def test_fresh_install_has_nothing_done() -> None:
    state = setup_state("fake", NOW)

    assert (state.broker_connected, state.instruments_synced_today) == (False, False)
    assert (state.instrument_count, state.agent_seen, state.first_fill_at) == (0, None, None)
    assert state.done is False


def test_each_step_comes_from_what_exists() -> None:
    save_credentials(Credentials("fake", "t", None, None))
    record_event(InstrumentSyncCompleted("fake", 1))
    note_client("claude-code", "stdio", "2.1.0", 1, NOW)
    desk = new_desk()  # lists RELIANCE
    desk.trade(Side.BUY, 1)

    state = setup_state("fake", datetime.now(UTC))

    assert state.broker_connected and state.instruments_synced_today
    assert state.instrument_count == 1 and state.agent_seen == "claude-code"
    assert state.first_fill_at is not None and state.done is True
