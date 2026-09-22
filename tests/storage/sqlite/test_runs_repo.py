from dataclasses import replace
from datetime import timedelta

from openticker.core.risk.models import PositionRisk, StrategyStopReason, TrailingStop, TrailMode
from openticker.core.strategies.runs import LegStatus, Run, RunLeg, RunStatus
from openticker.ports.models import Exchange, Product, Side
from openticker.storage.sqlite import runs_repo
from openticker.storage.sqlite.strategies_repo import write_transaction
from tests.fixtures.strategies import NOW

OPEN_LEG = RunLeg(
    leg_id="leg1",
    symbol="NIFTY22SEP262500CE",
    exchange=Exchange.NFO,
    side=Side.SELL,
    quantity=65,
    status=LegStatus.CLOSING,
    entry_price=100.0,
    entered_at=NOW,
    exit_reason="stop_loss",
    risk=PositionRisk(
        side=Side.SELL,
        entry_price=100.0,
        quantity=65,
        initial_sl=130.0,
        current_sl=110.0,
        target=50.0,
        highest_price=None,
        lowest_price=80.0,
        capital_cap=None,
        trailing=TrailingStop(TrailMode.CONTINUOUS, step=30.0, trigger=0.0),
    ),
    retry_at=NOW + timedelta(seconds=30),
    failed_exits=1,
)
CLOSED_LEG = RunLeg(
    "leg2",
    "NIFTY22SEP262500PE",
    Exchange.NFO,
    Side.SELL,
    65,
    LegStatus.CLOSED,
    entry_price=100.0,
    entered_at=NOW,
    exit_price=90.0,
    exit_reason="target",
)


def _run(**changes: object) -> Run:
    run = Run(
        id=runs_repo.new_run_id(),
        strategy_id="stg_1",
        broker="zerodha",
        product=Product.MIS,
        status=RunStatus.STOPPING,
        trigger="mcp",
        started_at=NOW,
        legs=(OPEN_LEG, CLOSED_LEG),
        peak_mtm=1200.0,
        lock_floor=500.0,
        stops_at_entry=True,
        stop_reason=StrategyStopReason.PROFIT_LOCK,
        stop_detail="fell to the floor",
    )
    return replace(run, **changes)  # type: ignore[arg-type]


def test_a_run_round_trips_with_every_leg_field_and_ratchet() -> None:
    run = _run()
    with write_transaction() as session:
        runs_repo.insert_run(session, run)

    assert runs_repo.find_run(run.id) == run
    assert [active.id for active in runs_repo.active_runs()] == [run.id]


def test_realized_since_sums_the_other_runs() -> None:
    earlier, current = _run(status=RunStatus.ENDED), _run()
    with write_transaction() as session:
        runs_repo.insert_run(session, earlier)
        runs_repo.insert_run(session, current)

    assert runs_repo.realized_since("stg_1", NOW, current.id) == 650.0
    assert runs_repo.realized_since("stg_1", NOW + timedelta(seconds=1), current.id) == 0.0
    assert runs_repo.realized_since("stg_2", NOW, current.id) == 0.0


def test_the_timeline_keeps_the_latest_in_order() -> None:
    for n in range(5):
        runs_repo.add_event("run_1", NOW + timedelta(seconds=n), f"event {n}")

    assert [e.message for e in runs_repo.list_events("run_1", 3)] == [
        "event 2",
        "event 3",
        "event 4",
    ]
