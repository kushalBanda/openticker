from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from openticker.core.agents.manager import (
    DEFAULT_WAKES_PER_DAY,
    OFF,
    ManagerLine,
    ManagerPlan,
    ManagerState,
    SetBy,
    parse_key,
)
from openticker.storage.sqlite import manager_repo
from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.models import ManagerStateRow

AT = datetime(2026, 9, 22, 4, 0, tzinfo=UTC)


def test_state_reads_off_when_no_row() -> None:
    assert manager_repo.get_state() == OFF


def test_state_round_trips() -> None:
    state = ManagerState(
        enabled=True,
        wakes_per_day=12,
        next_wake_at=AT,
        next_wake_reason="after the 10:00 data",
        last_wake_at=AT,
        last_audit_id=41,
        crossed=frozenset({"desk", "strategy:a"}),
        closed_on=date(2026, 9, 21),
        stalled="failing",
        plan=ManagerPlan(date(2026, 9, 22), "Run the straddle small.", ("les_1", "les_2"), AT),
        updated_at=AT,
    )
    with Session(get_engine()) as session:
        manager_repo.save_state(session, state)
        session.commit()
    assert manager_repo.get_state() == state


def test_null_wakes_per_day_reads_as_default() -> None:
    with Session(get_engine()) as session:
        session.add(ManagerStateRow(id=1, enabled=True))
        session.commit()
    state = manager_repo.get_state()
    assert state.enabled and state.wakes_per_day == DEFAULT_WAKES_PER_DAY
    assert state.plan is None and state.crossed == frozenset()


def test_lines_upsert_and_order() -> None:
    def line(key: str, capital: float) -> ManagerLine:
        return ManagerLine(
            parse_key(key), capital, -10.0, "why", SetBy.MANAGER, None, None, AT, "ui"
        )

    with Session(get_engine()) as session:
        for key in ("strategy:b", "script:s", "own", "strategy:a", "desk"):
            manager_repo.put_line(session, line(key, 1.0))
        manager_repo.put_line(session, line("strategy:a", 5.0))
        session.commit()
    found = manager_repo.lines()
    assert [str(x.key) for x in found] == ["desk", "own", "strategy:a", "strategy:b", "script:s"]
    assert found[2].capital == 5.0 and found[2].set_at == AT
