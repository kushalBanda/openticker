"""MCP clients seen calling tools (ADR 35 in docs/adr)."""

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.models import AgentClientRow


@dataclass(frozen=True)
class AgentClient:
    name: str
    transport: str  # stdio, http
    version: str | None
    first_seen_at: datetime  # tz-aware UTC
    last_seen_at: datetime
    calls: int


def note_client(name: str, transport: str, version: str | None, calls: int, now: datetime) -> None:
    """Adds `calls` to the client's count and moves its last sighting to `now`."""
    moment = now.astimezone(UTC).replace(tzinfo=None)
    with Session(get_engine()) as session:
        row = session.get(AgentClientRow, (name, transport))
        if row is None:
            session.add(
                AgentClientRow(
                    name=name,
                    transport=transport,
                    version=version,
                    first_seen_at=moment,
                    last_seen_at=moment,
                    calls=calls,
                )
            )
        else:
            row.version = version or row.version
            row.last_seen_at = moment
            row.calls += calls
        session.commit()


def list_clients() -> list[AgentClient]:
    """Most recently seen first."""
    with Session(get_engine()) as session:
        rows = session.scalars(
            select(AgentClientRow).order_by(AgentClientRow.last_seen_at.desc())
        ).all()
    return [
        AgentClient(
            name=row.name,
            transport=row.transport,
            version=row.version,
            first_seen_at=row.first_seen_at.replace(tzinfo=UTC),
            last_seen_at=row.last_seen_at.replace(tzinfo=UTC),
            calls=row.calls,
        )
        for row in rows
    ]
