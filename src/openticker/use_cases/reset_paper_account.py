"""Reset the paper account: a full wipe (ADR 37 in docs/adr).

Every paper order, trade and position is deleted, with the P&L recorded by
day and by minute (ADR 34), and the funds go back to the starting capital. The audit log, strategies, their runs and scripts
stay; a strategy's ledger, built from its trades, starts again from zero.
Refused while a strategy or a script runs: either could place an order into
the account as it is wiped. The check runs under the same write lock as the
wipe, so nothing can start in between.
"""

from datetime import datetime

from openticker.events.bus import EventPublisher
from openticker.events.types import PaperAccountReset
from openticker.storage.sqlite import pnl_repo, runs_repo, scripts_repo
from openticker.storage.sqlite.sandbox_repo import fill_transaction, reset_account
from openticker.storage.sqlite.scripts_repo import load_script
from openticker.storage.sqlite.strategies_repo import load_strategy

CONFIRMATION = "RESET"


class ResetConfirmationError(ValueError):
    pass


class ResetRefusedError(Exception):
    """Something is running; the message names it."""


def reset_paper_account(
    confirm: str, capital: float, events: EventPublisher, now: datetime, triggered_by: str
) -> PaperAccountReset:
    if confirm != CONFIRMATION:
        raise ResetConfirmationError(
            f"type {CONFIRMATION} to confirm: the reset deletes every paper order, trade "
            "and position and can't be undone"
        )
    with fill_transaction() as session:
        running = []
        for run in runs_repo.active_runs(session):
            strategy = load_strategy(session, run.strategy_id)
            running.append(f"strategy {strategy.name if strategy else run.strategy_id}")
        for script_run in scripts_repo.active_runs(session):
            script = load_script(session, script_run.script_id)
            running.append(f"script {script.name if script else script_run.script_id}")
        if running:
            raise ResetRefusedError(
                f"Stop {', '.join(running)} first. A running strategy or script could "
                "place an order while the account is wiped."
            )
        wiped = reset_account(session, capital)
        pnl_repo.delete_all(session)
    event = PaperAccountReset(
        capital=capital,
        orders=wiped.orders,
        trades=wiped.trades,
        positions=wiped.positions,
        triggered_by=triggered_by,
        occurred_at=now,
    )
    events.publish(event)
    return event
