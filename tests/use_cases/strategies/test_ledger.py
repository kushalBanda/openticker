from datetime import timedelta

import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from openticker.adapters.sandbox.broker import SandboxSettings
from openticker.core.orders.fills import FillSettings
from openticker.storage.sqlite.engine import get_engine
from openticker.storage.sqlite.models import SandboxTradeRow
from openticker.use_cases.strategies.control import request_start, request_stop
from openticker.use_cases.strategies.define import UnknownStrategyError
from openticker.use_cases.strategies.ledger import get_strategy_ledger
from openticker.use_cases.strategies.runner import process_commands
from tests.fixtures.strategy_desk import LOT, Desk

# Real charges from the shipped rates, and one tick of slippage: the fake
# quotes carry no book, so every fill pays the last price moved a tick.
COSTED = SandboxSettings(fills=FillSettings(slippage_ticks=1))


def _stop(desk: Desk, strategy_id: str) -> None:
    request_stop(strategy_id, "mcp", desk.now)
    process_commands(desk.context, desk.now)


def _restart(desk: Desk, strategy_id: str) -> None:
    desk.now += timedelta(minutes=5)
    request_start(strategy_id, "fake", "mcp", desk.now)
    process_commands(desk.context, desk.now)


@pytest.fixture
def desk() -> Desk:
    return Desk(COSTED)


def test_a_run_nets_its_charges_and_shows_each_fill(desk: Desk) -> None:
    strategy_id = desk.start()
    desk.tick(ce=90.0, pe=95.0)
    _stop(desk, strategy_id)

    ledger = get_strategy_ledger(strategy_id, 20)

    [run] = ledger.runs
    trades = desk.sandbox.get_trades(desk.now - timedelta(days=1), 10)
    assert len(run.fills) == 4 and run.after_costs
    assert run.charges == round(sum(t.charges or 0.0 for t in trades), 2) > 0
    assert run.net_pnl == round(run.gross_pnl - run.charges, 2)
    assert run.slippage == round(4 * 0.05 * LOT, 2)  # a tick on each fill, all against
    assert (ledger.totals.runs, ledger.totals.net_pnl) == (1, run.net_pnl)


def test_totals_leave_out_open_and_uncharged_runs(desk: Desk) -> None:
    strategy_id = desk.start()
    _stop(desk, strategy_id)
    first = desk.run(strategy_id).id
    _restart(desk, strategy_id)
    _stop(desk, strategy_id)
    _restart(desk, strategy_id)  # left open
    with Session(get_engine()) as session, session.begin():
        session.execute(
            update(SandboxTradeRow).where(SandboxTradeRow.run_id == first).values(charges=None)
        )

    ledger = get_strategy_ledger(strategy_id, 2)

    assert (ledger.total_runs, ledger.uncharged, ledger.open_runs) == (3, 1, 1)
    assert ledger.totals.runs == 1
    assert [r.run.status for r in ledger.runs] == ["open", "ended"]  # newest first, 2 asked


def test_an_unknown_strategy_says_where_to_look() -> None:
    with pytest.raises(UnknownStrategyError, match="list_strategies"):
        get_strategy_ledger("stg_nope", 20)
