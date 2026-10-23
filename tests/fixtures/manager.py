"""The desk manager's state for tests that need a line to hold something out."""

from dataclasses import replace
from datetime import datetime

from openticker.core.agents.manager import ManagerLine, SetBy, parse_key
from openticker.storage.sqlite import manager_repo
from openticker.storage.sqlite.strategies_repo import write_transaction


def hold_out(key: str, at: datetime, enabled: bool = True) -> None:
    """Turns the manager on (or off) and gives `key` a line of its own at
    capital 0, set `at`: it holds for that trading day (ADR 46)."""
    with write_transaction() as session:
        state = manager_repo.get_state(session)
        manager_repo.save_state(session, replace(state, enabled=enabled))
        manager_repo.put_line(
            session,
            ManagerLine(parse_key(key), 0.0, None, "held", SetBy.MANAGER, 0.0, None, at, "manager"),
        )
