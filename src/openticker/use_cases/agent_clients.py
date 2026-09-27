"""Which MCP clients use OpenTicker (ADR 35 in docs/adr). Every tool call
notes its client; the table is written at most once a minute per client,
with the calls counted in between."""

import threading
from datetime import datetime, timedelta

from openticker.storage.sqlite import agent_clients_repo
from openticker.storage.sqlite.agent_clients_repo import AgentClient

NOTE_EVERY = timedelta(minutes=1)

_lock = threading.Lock()
_written: dict[tuple[str, str], datetime] = {}  # when each client was last written
_unwritten: dict[tuple[str, str], int] = {}  # calls since then


def note_agent_client(name: str, transport: str, version: str | None, now: datetime) -> None:
    key = (name, transport)
    with _lock:
        calls = _unwritten.get(key, 0) + 1
        last = _written.get(key)
        if last is not None and now - last < NOTE_EVERY:
            _unwritten[key] = calls
            return
        _written[key] = now
        _unwritten[key] = 0
    agent_clients_repo.note_client(name, transport, version, calls, now)


def get_agent_clients() -> list[AgentClient]:
    return agent_clients_repo.list_clients()


def forget_noted() -> None:
    """For tests: the next call of each client is written."""
    with _lock:
        _written.clear()
        _unwritten.clear()
