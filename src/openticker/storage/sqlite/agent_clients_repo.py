"""MCP clients seen calling tools (ADR 35 in docs/adr)."""

from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from openticker.ports.models import EXCHANGE_TIMEZONE
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
    last_tool: str | None = None  # None: not kept when it was last written
    day: date | None = None  # exchange-local day `calls_today` counts
    calls_today: int = 0


def note_client(
    name: str,
    transport: str,
    version: str | None,
    calls: int,
    now: datetime,
    tool: str | None = None,
) -> None:
    """Adds `calls` to the client's count and to the day's, and moves its
    last sighting to `now`. A new day starts the day's count again."""
    moment = now.astimezone(UTC).replace(tzinfo=None)
    today = now.astimezone(EXCHANGE_TIMEZONE).date()
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
                    last_tool=tool,
                    day=today,
                    calls_today=calls,
                )
            )
        else:
            row.version = version or row.version
            row.last_seen_at = moment
            row.calls += calls
            row.last_tool = tool or row.last_tool
            row.calls_today = (row.calls_today or 0) + calls if row.day == today else calls
            row.day = today
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
            last_tool=row.last_tool,
            day=row.day,
            calls_today=row.calls_today or 0,
        )
        for row in rows
    ]
