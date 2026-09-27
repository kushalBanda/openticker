"""Which MCP clients use OpenTicker (ADR 35 in docs/adr). Every tool call
notes its client; the table is written at most once a minute per client,
with the calls counted in between."""

import threading
from dataclasses import replace
from datetime import datetime, timedelta

from openticker.ports.models import EXCHANGE_TIMEZONE
from openticker.storage.sqlite import agent_clients_repo
from openticker.storage.sqlite.agent_clients_repo import AgentClient

NOTE_EVERY = timedelta(minutes=1)

_lock = threading.Lock()
_written: dict[tuple[str, str], datetime] = {}  # when each client was last written
_unwritten: dict[tuple[str, str], int] = {}  # calls since then


def note_agent_client(
    name: str, transport: str, version: str | None, now: datetime, tool: str | None = None
) -> None:
    """`tool`: the one it called. The written row names the last tool of the
    calls it counts, so it can be up to a minute behind."""
    key = (name, transport)
    with _lock:
        calls = _unwritten.get(key, 0) + 1
        last = _written.get(key)
        if last is not None and now - last < NOTE_EVERY:
            _unwritten[key] = calls
            return
        _written[key] = now
        _unwritten[key] = 0
    agent_clients_repo.note_client(name, transport, version, calls, now, tool)


def get_agent_clients(now: datetime | None = None) -> list[AgentClient]:
    """With `now`, a client not seen on its exchange-local day has made no
    calls today, whatever its last day's count."""
    clients = agent_clients_repo.list_clients()
    if now is None:
        return clients
    today = now.astimezone(EXCHANGE_TIMEZONE).date()
    return [c if c.day == today else replace(c, calls_today=0) for c in clients]


def forget_noted() -> None:
    """For tests: the next call of each client is written."""
    with _lock:
        _written.clear()
        _unwritten.clear()
