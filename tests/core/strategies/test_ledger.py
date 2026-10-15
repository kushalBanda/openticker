from datetime import UTC, datetime, timedelta

from openticker.core.pnl import DayFigure
from openticker.core.risk.models import StrategyLimits, StrategyStopReason
from openticker.core.strategies.ledger import (
    LedgerFill,
    LedgerRun,
    SuggestedStop,
    day_figure,
    equity_curve,
    ledger_totals,
    suggest_stop,
)
from openticker.core.strategies.runs import LegStatus, Run, RunLeg, RunStatus
from openticker.ports.models import Exchange, Product, Side

START = datetime(2026, 9, 22, 4, 0, tzinfo=UTC)
SYMBOL = "NIFTY22SEP2625000CE"


def _fill(
    side: Side,
    price: float,
    expected: float | None = None,
    charges: float | None = 5.0,
    realized: float | None = None,
    at: datetime = START,
) -> LedgerFill:
    return LedgerFill(SYMBOL, "NFO", side, 10, price, at, expected, charges, realized)


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


def test_a_day_counts_the_fills_filled_that_day_whichever_day_the_run_started() -> None:
    # A positional run: sold on the 22nd, bought back on the 23rd for 300.
    entry = _fill(Side.SELL, 100.0, charges=8.0, realized=0.0)
    exit_ = _fill(Side.BUY, 70.0, charges=12.5, realized=300.0, at=START + timedelta(days=1))
    positional = LedgerRun(_run(0, 300.0).run, (entry, exit_))
    # One opened and closed on the 23rd.
    same_day = LedgerRun(
        _run(1, -40.0).run,
        (
            _fill(Side.SELL, 100.0, charges=4.0, realized=0.0, at=START + timedelta(days=1)),
            _fill(Side.BUY, 104.0, charges=6.0, realized=-40.0, at=START + timedelta(days=1)),
        ),
    )
    day = (START + timedelta(days=1)).date()

    figure = day_figure([positional, same_day], day)

    assert figure == DayFigure(gross=260.0, charges=22.5)
    assert figure.net == 237.5
    assert day_figure([positional, same_day], START.date()) == DayFigure(gross=0.0, charges=8.0)


def test_a_fill_that_never_recorded_what_it_realized_counts_its_charges_only() -> None:
    old = LedgerRun(_run(0, 50.0).run, (_fill(Side.BUY, 95.0, charges=3.0),))

    assert day_figure([old], START.date()) == DayFigure(gross=0.0, charges=3.0)


def test_equity_adds_up_judged_runs_by_the_day_they_started() -> None:
    runs = [
        _run(2, 50.0),
        _run(1, -300.0, status=RunStatus.OPEN),  # not judged
        _run(1, 100.0, charges=None),  # not judged
        _run(0, 200.0),
    ]
    runs.append(_run(0, 40.0))

    curve = equity_curve(runs)

    assert [(point.day.day, point.net_pnl) for point in curve] == [
        (22, 220.0),
        (24, 260.0),
    ]  # less 10 charges a run


def test_equity_keeps_the_latest_days_when_there_are_too_many() -> None:
    curve = equity_curve([_run(day, 20.0) for day in range(5)], limit=2)  # nets 10 a day

    assert [point.net_pnl for point in curve] == [40.0, 50.0]


def _record(losers: list[float], winners: int) -> list[LedgerRun]:
    """Runs after costs: each loser's net as given (charges 10), then winners of +990."""
    nets = [*losers, *([990.0] * winners)]
    return [_run(day, net + 10.0) for day, net in enumerate(nets)]


def test_suggest_stop_is_the_multiple_of_the_median_losing_run() -> None:
    runs = _record([-4000.0, -5000.0, -5000.0, -6000.0, -9000.0], winners=7)
    assert suggest_stop(runs, StrategyLimits()) == SuggestedStop(
        -8750.0, "1.75x its median losing run -₹5,000 over 12 runs after costs"
    )


def test_suggest_stop_is_never_tighter_than_its_own_combined_stop() -> None:
    runs = _record([-2000.0] * 4, winners=8)  # 1.75x gives -3,500
    found = suggest_stop(runs, StrategyLimits(combined_stop_loss=10_000.0))
    assert found is not None and found.value == -10_000.0
    assert found.basis.startswith("its own combined stop -₹10,000; 1.75x its median")
    # a daily loss limit is no floor: it caps a whole day, not a run
    found = suggest_stop(runs, StrategyLimits(daily_loss_limit=10_000.0))
    assert found is not None and found.value == -3500.0


def test_a_thin_record_uses_its_own_combined_stop_else_its_daily_limit() -> None:
    runs = _record([-2000.0], winners=3)
    found = suggest_stop(runs, StrategyLimits(combined_stop_loss=3000.0, daily_loss_limit=9000.0))
    assert found == SuggestedStop(
        -3000.0, "its own combined stop -₹3,000; 4 runs after costs, fewer than 10"
    )
    found = suggest_stop(runs, StrategyLimits(daily_loss_limit=9000.0))
    assert found == SuggestedStop(
        -9000.0, "its own daily loss limit -₹9,000; 4 runs after costs, fewer than 10"
    )


def test_no_record_and_no_own_stop_suggests_nothing() -> None:
    assert suggest_stop([], StrategyLimits()) is None
    one = suggest_stop(_record([-100.0], winners=0), StrategyLimits(combined_stop_loss=500.0))
    assert one is not None and "; 1 run after costs," in one.basis
    assert suggest_stop(_record([], winners=12), StrategyLimits()) is None  # never lost
