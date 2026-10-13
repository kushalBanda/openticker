"""The defaults the web app's Settings set for the user's coding agent (ADR 40
in docs/adr). A missing row or a NULL value: from the environment."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from openticker.core.agents.choices import Effort, FolderKind, RunChoice, StoredSettings
from openticker.core.agents.jobs import Harness
from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.models import AgentSettingRow

ALL = "all"  # the row for every folder: the harness, and runs a day


def stored_settings() -> StoredSettings:
    with Session(get_engine()) as session:
        rows = {row.kind: row for row in session.scalars(select(AgentSettingRow)).all()}
    every = rows.pop(ALL, None)
    return StoredSettings(
        harness=Harness(every.harness) if every and every.harness else None,
        runs_per_day=every.runs_per_day if every else None,
        choices={FolderKind(kind): _choice(row) for kind, row in rows.items() if kind in _KINDS},
        chosen_for={
            FolderKind(kind): Harness(row.chosen_for)
            for kind, row in rows.items()
            if kind in _KINDS and row.chosen_for
        },
    )


def save_choice(
    session: Session, kind: FolderKind, choice: RunChoice, chosen_for: Harness, now: datetime
) -> None:
    """`chosen_for`: the harness the choice's model and effort are meant for."""
    row = _row(session, kind.value, now)
    row.harness = choice.harness.value if choice.harness else None
    row.chosen_for = chosen_for.value
    row.model = choice.model
    row.effort = choice.effort.value if choice.effort else None
    row.max_budget_usd = choice.max_budget_usd
    row.timeout_minutes = int(choice.timeout.total_seconds() // 60) if choice.timeout else None


def save_harness(session: Session, harness: Harness | None, now: datetime) -> None:
    _row(session, ALL, now).harness = harness.value if harness else None


def save_runs_per_day(session: Session, count: int | None, now: datetime) -> None:
    _row(session, ALL, now).runs_per_day = count


def clear(session: Session) -> None:
    session.execute(delete(AgentSettingRow))


_KINDS = {kind.value for kind in FolderKind}


def _row(session: Session, kind: str, now: datetime) -> AgentSettingRow:
    row = session.get(AgentSettingRow, kind)
    if row is None:
        row = AgentSettingRow(kind=kind)
        session.add(row)
    row.updated_at = now.astimezone(UTC).replace(tzinfo=None)
    return row


def _choice(row: AgentSettingRow) -> RunChoice:
    return RunChoice(
        harness=Harness(row.harness) if row.harness else None,
        model=row.model,
        effort=Effort(row.effort) if row.effort else None,
        max_budget_usd=row.max_budget_usd,
        timeout=timedelta(minutes=row.timeout_minutes) if row.timeout_minutes else None,
    )
