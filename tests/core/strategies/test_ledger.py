from datetime import UTC, datetime, timedelta

from openticker.core.risk.models import StrategyStopReason
from openticker.core.strategies.ledger import LedgerFill, LedgerRun, ledger_totals
from openticker.core.strategies.runs import LegStatus, Run, RunLeg, RunStatus
from openticker.ports.models import Exchange, Product, Side

START = datetime(2026, 9, 22, 4, 0, tzinfo=UTC)
SYMBOL = "NIFTY22SEP2625000CE"


def _fill(
    side: Side, price: float, expected: float | None = None, charges: float | None = 5.0
) -> LedgerFill:
    return LedgerFill(SYMBOL, "NFO", side, 10, price, START, expected, charges)


def _run(
    day: int,
    gross: float,
    charges: float | None = 10.0,
    status: RunStatus = RunStatus.ENDED,
    reason: StrategyStopReason = StrategyStopReason.SCHEDULE,
) -> LedgerRun:
    """A short leg of 10 sold at 100 and bought back to make `gross`."""
    leg = RunLeg(
        "ce",
        SYMBOL,
        Exchange.NFO,
        Side.SELL,
        10,
        LegStatus.CLOSED,
        entry_price=100.0,
        exit_price=100.0 - gross / 10,
    )
    run = Run(
        id=f"run{day}",
        strategy_id="stg",
        broker="fake",
        product=Product.NRML,
        status=status,
        trigger="schedule",
        started_at=START + timedelta(days=day),
        legs=(leg,),
        stop_reason=reason if status is RunStatus.ENDED else None,
    )
    half = None if charges is None else charges / 2
    fills = (
        _fill(Side.SELL, 100.0, charges=half),
        _fill(Side.BUY, 100.0 - gross / 10, charges=half),
    )
    return LedgerRun(run, fills)


def test_slippage_is_a_cost_when_the_fill_is_worse_either_way() -> None:
    assert _fill(Side.BUY, 100.05, expected=100.0).slippage == 0.5
    assert _fill(Side.SELL, 99.95, expected=100.0).slippage == 0.5
    assert _fill(Side.SELL, 100.05, expected=100.0).slippage == -0.5  # better than expected
    assert _fill(Side.BUY, 100.0).slippage is None  # filled before costs


def test_a_runs_net_is_its_gross_less_its_charges() -> None:
    run = _run(0, gross=200.0, charges=30.0)

    assert (run.gross_pnl, run.charges, run.net_pnl) == (200.0, 30.0, 170.0)


def test_only_ended_runs_that_paid_charges_are_judged() -> None:
    assert _run(0, 100.0).after_costs
    assert not _run(1, 100.0, charges=None).after_costs  # before costs
    assert not _run(2, 100.0, status=RunStatus.OPEN).after_costs
    assert not LedgerRun(_run(3, 0.0).run, ()).after_costs  # never filled


def test_totals_judge_runs_after_costs_only() -> None:
    runs = [
        _run(0, 300.0),  # net 290
        _run(1, -500.0, reason=StrategyStopReason.COMBINED_STOP_LOSS),  # net -510
        _run(2, 100.0),  # net 90
        _run(3, 5.0),  # net -5: a win before charges, a loss after
        _run(4, 10_000.0, charges=None),  # before costs: left out
        _run(5, 10_000.0, status=RunStatus.OPEN),  # open: left out
    ]

    totals = ledger_totals(runs)

    assert (totals.runs, totals.wins, totals.losses) == (4, 2, 2)
    assert (totals.gross_pnl, totals.charges, totals.net_pnl) == (-95.0, 40.0, -135.0)
    assert (totals.average_win, totals.average_loss) == (190.0, -257.5)
    assert (totals.best_run, totals.worst_run) == (290.0, -510.0)
    assert totals.stop_reasons == {"schedule": 3, "combined_stop_loss": 1}


def test_drawdown_is_the_deepest_fall_from_a_high_in_run_order() -> None:
    # Nets in start order: +300, -200, +300, -200; cumulative 300, 100, 400, 200.
    # Taken in the order given instead, it would be 300, 600, 400, 200: a fall of 400.
    runs = [_run(0, 310.0), _run(2, 310.0), _run(1, -190.0), _run(3, -190.0)]

    assert ledger_totals(runs).max_drawdown == 200.0


def test_no_runs_judged_yet() -> None:
    totals = ledger_totals([_run(0, 100.0, charges=None)])

    assert (totals.runs, totals.net_pnl, totals.best_run, totals.max_drawdown) == (
        0,
        0.0,
        None,
        0.0,
    )
    assert totals.average_win is None and totals.stop_reasons == {}
