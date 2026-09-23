from dataclasses import replace
from datetime import time, timedelta

import pytest

from openticker.core.orders.models import OrderRequest, OrderType
from openticker.core.risk.models import StrategyLimits, StrategyStopReason
from openticker.core.strategies.models import (
    Horizon,
    RiskValue,
    Schedule,
    SignalLeg,
    SignalStrategySpec,
)
from openticker.core.strategies.runs import (
    Command,
    CommandKind,
    CommandStatus,
    LegStatus,
    Run,
    RunLeg,
    RunStatus,
)
from openticker.core.strategies.signals import SignalAction
from openticker.events.types import StrategyStarted, StrategyStopped
from openticker.ports.models import Exchange, Product, Side
from openticker.storage.sqlite import runs_repo
from openticker.storage.sqlite.instruments_repo import get_instrument
from openticker.storage.sqlite.runs_repo import WEBHOOK_TRIGGER
from openticker.storage.sqlite.strategies_repo import write_transaction
from openticker.use_cases.strategies.control import request_kill, request_stop
from openticker.use_cases.strategies.define import create_strategy
from openticker.use_cases.strategies.runner import START_TIMEOUT, process_commands, step_runs
from tests.fixtures.strategy_desk import CE, LOT, PE, Desk

SIGNALLED = SignalStrategySpec(
    legs=(SignalLeg(CE, Exchange.NFO, LOT), SignalLeg(PE, Exchange.NFO, LOT)),
    horizon=Horizon.INTRADAY,
)


class SignalDesk(Desk):
    def create(self, spec: SignalStrategySpec = SIGNALLED, name: str = "alerts") -> str:
        return create_strategy(name, spec, self.now).id

    def signal(self, strategy_id: str, leg_id: str, action: SignalAction) -> Command:
        with write_transaction() as session:
            command = runs_repo.add_command(
                session,
                strategy_id,
                CommandKind.SIGNAL,
                WEBHOOK_TRIGGER,
                self.now,
                broker="fake",
                leg_id=leg_id,
                action=action,
            )
        process_commands(self.context, self.now)
        return next(c for c in runs_repo.recent_commands(strategy_id, 20) if c.id == command.id)

    def only_run(self, strategy_id: str) -> Run:
        runs = runs_repo.list_runs(strategy_id, 5)
        assert len(runs) == 1
        return runs[0]


@pytest.fixture
def desk() -> SignalDesk:
    return SignalDesk()


def _legs(run: Run) -> list[tuple[str, Side, LegStatus]]:
    return [(leg.leg_id, leg.side, leg.status) for leg in run.legs]


def test_the_first_entry_opens_the_days_run(desk: SignalDesk) -> None:
    strategy_id = desk.create()

    command = desk.signal(strategy_id, "leg1", SignalAction.LONG_ENTRY)

    assert (command.status, command.outcome) == (CommandStatus.DONE, "entering long: leg1")
    run = desk.only_run(strategy_id)
    assert (run.status, run.trigger, run.product) == (RunStatus.OPEN, "webhook", Product.MIS)
    assert _legs(run) == [("leg1", Side.BUY, LegStatus.OPEN)]
    assert run.legs[0].entry_price == 100.0 and run.legs[0].spec_leg == "leg1"
    assert desk.held() == {CE: LOT}
    orders = runs_repo.list_orders(run.id)
    assert [(o.leg_id, o.intent, o.side, o.status) for o in orders] == [
        ("leg1", "entry", Side.BUY, "FILLED")
    ]
    started = desk.events.of(StrategyStarted)
    assert [(s.run_id, s.triggered_by) for s in started] == [  # type: ignore[attr-defined]
        (run.id, "webhook")
    ]


def test_repeated_alerts_do_nothing(desk: SignalDesk) -> None:
    strategy_id = desk.create()
    desk.signal(strategy_id, "leg1", SignalAction.LONG_ENTRY)

    again = desk.signal(strategy_id, "leg1", SignalAction.LONG_ENTRY)
    no_short = desk.signal(strategy_id, "leg1", SignalAction.SHORT_EXIT)
    flat_leg = desk.signal(strategy_id, "leg2", SignalAction.LONG_EXIT)

    assert [(c.status, c.outcome) for c in (again, no_short, flat_leg)] == [
        (CommandStatus.DONE, "already long"),
        (CommandStatus.DONE, "no short position to exit"),
        (CommandStatus.DONE, "no long position to exit"),
    ]
    assert len(runs_repo.list_orders(desk.only_run(strategy_id).id)) == 1
    assert desk.held() == {CE: LOT}


def test_an_exit_leaves_the_run_waiting_and_the_leg_can_enter_again(desk: SignalDesk) -> None:
    strategy_id = desk.create()
    desk.signal(strategy_id, "leg1", SignalAction.LONG_ENTRY)
    desk.market.prices[CE] = 110.0

    exited = desk.signal(strategy_id, "leg1", SignalAction.LONG_EXIT)
    desk.tick()

    assert exited.outcome == "exiting the long: leg1"
    run = desk.only_run(strategy_id)
    assert run.status is RunStatus.OPEN and run.realized_pnl == 10.0 * LOT
    assert run.legs[0].exit_reason == "signal"
    assert desk.held() == {}

    desk.signal(strategy_id, "leg1", SignalAction.SHORT_ENTRY)
    desk.signal(strategy_id, "leg1", SignalAction.SHORT_EXIT)
    desk.signal(strategy_id, "leg1", SignalAction.LONG_ENTRY)

    run = desk.only_run(strategy_id)
    assert _legs(run) == [
        ("leg1", Side.BUY, LegStatus.CLOSED),
        ("leg1.2", Side.SELL, LegStatus.CLOSED),
        ("leg1.3", Side.BUY, LegStatus.OPEN),
    ]
    assert {leg.spec_leg for leg in run.legs} == {"leg1"}
    assert desk.held() == {CE: LOT}
    assert len(desk.events.of(StrategyStarted)) == 1  # only the entry that opened the run


def test_an_entry_the_other_way_closes_the_position_first(desk: SignalDesk) -> None:
    strategy_id = desk.create()
    desk.signal(strategy_id, "leg2", SignalAction.SHORT_ENTRY)
    desk.market.prices[PE] = 90.0

    flipped = desk.signal(strategy_id, "leg2", SignalAction.LONG_ENTRY)

    assert flipped.outcome == "closing the short, then entering long: leg2.2"
    run = desk.only_run(strategy_id)
    assert _legs(run) == [
        ("leg2", Side.SELL, LegStatus.CLOSED),
        ("leg2.2", Side.BUY, LegStatus.OPEN),
    ]
    assert run.realized_pnl == 10.0 * LOT
    assert desk.held() == {PE: LOT}


def test_a_flip_whose_exit_fails_enters_nothing(desk: SignalDesk) -> None:
    strategy_id = desk.create()
    desk.signal(strategy_id, "leg1", SignalAction.LONG_ENTRY)
    desk.market.down_for.add(CE)

    flipped = desk.signal(strategy_id, "leg1", SignalAction.SHORT_ENTRY)

    assert flipped.status is CommandStatus.REFUSED
    assert "leg1's exit has not filled, so no short_entry was entered" in (flipped.outcome or "")
    assert _legs(desk.only_run(strategy_id)) == [("leg1", Side.BUY, LegStatus.CLOSING)]
    later = desk.signal(strategy_id, "leg1", SignalAction.SHORT_ENTRY)
    assert later.status is CommandStatus.REFUSED
    assert later.outcome == "leg1 is closing; send the alert again once it settles"


def test_a_legs_own_stop_closes_it_and_the_run_waits(desk: SignalDesk) -> None:
    guarded = SignalStrategySpec(
        legs=(SignalLeg(CE, Exchange.NFO, LOT, stop_loss=RiskValue(10.0, percent=False)),),
        horizon=Horizon.INTRADAY,
    )
    strategy_id = desk.create(guarded)
    desk.signal(strategy_id, "leg1", SignalAction.SHORT_ENTRY)

    desk.tick(ce=111.0)

    run = desk.only_run(strategy_id)
    assert run.status is RunStatus.OPEN
    assert [(leg.status, leg.exit_reason) for leg in run.legs] == [(LegStatus.CLOSED, "stop_loss")]
    assert run.legs[0].risk is not None and run.legs[0].risk.side is Side.SELL


def test_the_strategy_limits_end_the_run_and_the_next_entry_opens_another(
    desk: SignalDesk,
) -> None:
    limited = SignalStrategySpec(
        legs=SIGNALLED.legs,
        horizon=Horizon.INTRADAY,
        limits=StrategyLimits(combined_stop_loss=1000.0),
    )
    strategy_id = desk.create(limited)
    desk.signal(strategy_id, "leg1", SignalAction.LONG_ENTRY)
    desk.signal(strategy_id, "leg2", SignalAction.LONG_ENTRY)

    desk.tick(ce=90.0, pe=90.0)  # -1,300

    first = desk.only_run(strategy_id)
    assert (first.status, first.stop_reason) == (
        RunStatus.ENDED,
        StrategyStopReason.COMBINED_STOP_LOSS,
    )
    desk.signal(strategy_id, "leg1", SignalAction.LONG_ENTRY)
    runs = runs_repo.list_runs(strategy_id, 5)
    assert [run.status for run in runs] == [RunStatus.OPEN, RunStatus.ENDED]


def test_a_flat_run_ends_at_exit_time_or_the_sessions_close(desk: SignalDesk) -> None:
    timed = SignalStrategySpec(
        legs=SIGNALLED.legs, horizon=Horizon.INTRADAY, schedule=Schedule(exit_time=time(14, 0))
    )
    strategy_id = desk.create(timed)
    desk.signal(strategy_id, "leg1", SignalAction.LONG_ENTRY)
    desk.signal(strategy_id, "leg1", SignalAction.LONG_EXIT)

    desk.now = desk.now.replace(hour=8, minute=29)  # 13:59 IST
    step_runs(desk.context, desk.now)
    assert desk.only_run(strategy_id).status is RunStatus.OPEN
    desk.now += timedelta(minutes=1)
    step_runs(desk.context, desk.now)

    run = desk.only_run(strategy_id)
    assert (run.status, run.stop_reason, run.stop_detail) == (
        RunStatus.ENDED,
        StrategyStopReason.SCHEDULE,
        "exit_time 14:00",
    )
    stopped = desk.events.of(StrategyStopped)
    assert [s.reason for s in stopped] == ["schedule"]  # type: ignore[attr-defined]

    untimed = desk.create(name="untimed")
    desk.now = desk.now.replace(hour=9, minute=0)  # 14:30 IST
    desk.signal(untimed, "leg1", SignalAction.LONG_ENTRY)
    desk.signal(untimed, "leg1", SignalAction.LONG_EXIT)
    desk.now = desk.now.replace(hour=9, minute=59)  # 15:29 IST
    step_runs(desk.context, desk.now)
    assert runs_repo.list_runs(untimed, 1)[0].status is RunStatus.OPEN
    desk.now += timedelta(minutes=1)
    step_runs(desk.context, desk.now)
    assert runs_repo.list_runs(untimed, 1)[0].stop_detail == "the session ended"


def test_stop_closes_the_days_run(desk: SignalDesk) -> None:
    strategy_id = desk.create()
    desk.signal(strategy_id, "leg1", SignalAction.LONG_ENTRY)

    request_stop(strategy_id, "mcp", desk.now)
    process_commands(desk.context, desk.now)

    run = desk.only_run(strategy_id)
    assert (run.status, run.stop_reason) == (RunStatus.ENDED, StrategyStopReason.MANUAL)
    assert desk.held() == {}


def test_signals_are_refused_once_killed_late_or_after_the_square_off(desk: SignalDesk) -> None:
    strategy_id = desk.create()
    with write_transaction() as session:
        stale = runs_repo.add_command(
            session,
            strategy_id,
            CommandKind.SIGNAL,
            WEBHOOK_TRIGGER,
            desk.now - START_TIMEOUT - timedelta(seconds=1),
            broker="fake",
            leg_id="leg1",
            action=SignalAction.LONG_ENTRY,
        )
    process_commands(desk.context, desk.now)
    settled = runs_repo.commands_by_id([stale.id])[stale.id]
    assert settled.status is CommandStatus.REFUSED
    assert (settled.outcome or "").startswith("expired")

    desk.now = desk.now.replace(hour=9, minute=46)  # 15:16 IST, past the MIS square-off
    late = desk.signal(strategy_id, "leg1", SignalAction.LONG_ENTRY)
    assert late.status is CommandStatus.REFUSED and "intraday square-off" in (late.outcome or "")

    request_kill(strategy_id, "mcp", desk.now)
    process_commands(desk.context, desk.now)
    killed = desk.signal(strategy_id, "leg1", SignalAction.LONG_ENTRY)
    assert (killed.status, killed.outcome) == (CommandStatus.REFUSED, "locked by its kill switch")
    assert runs_repo.list_runs(strategy_id, 5) == []


def test_kill_cancels_signals_not_yet_carried_out(desk: SignalDesk) -> None:
    strategy_id = desk.create()
    with write_transaction() as session:
        queued = runs_repo.add_command(
            session,
            strategy_id,
            CommandKind.SIGNAL,
            WEBHOOK_TRIGGER,
            desk.now,
            broker="fake",
            leg_id="leg1",
            action=SignalAction.LONG_ENTRY,
        )

    request_kill(strategy_id, "mcp", desk.now)

    settled = runs_repo.commands_by_id([queued.id])[queued.id]
    assert (settled.status, settled.outcome) == (
        CommandStatus.REFUSED,
        "cancelled by the kill switch",
    )


def test_a_failed_entry_leaves_the_run_waiting(desk: SignalDesk) -> None:
    strategy_id = desk.create()
    desk.signal(strategy_id, "leg1", SignalAction.LONG_ENTRY)
    desk.market.down_for.add(PE)

    desk.signal(strategy_id, "leg2", SignalAction.LONG_ENTRY)
    desk.tick()

    run = desk.only_run(strategy_id)
    assert run.status is RunStatus.OPEN
    assert [leg.status for leg in run.legs] == [LegStatus.OPEN, LegStatus.FAILED]


def _lost_entry(desk: SignalDesk, strategy_id: str, filled: bool) -> Run:
    """leg1 held; leg2 exited, then re-entered short as leg2.2, and the daemon
    died once the order was recorded: before sending it, or after the sandbox
    filled it."""
    desk.signal(strategy_id, "leg1", SignalAction.LONG_ENTRY)
    desk.signal(strategy_id, "leg2", SignalAction.LONG_ENTRY)
    desk.signal(strategy_id, "leg2", SignalAction.LONG_EXIT)
    run = desk.only_run(strategy_id)
    pending = RunLeg("leg2.2", PE, Exchange.NFO, Side.SELL, LOT, LegStatus.PENDING, spec_leg="leg2")
    runs_repo.save_run(replace(run, legs=(*run.legs, pending)))
    runs_repo.add_order(run.id, pending, "entry", Side.SELL, LOT, desk.now)
    instrument = get_instrument(PE, "NFO")
    assert instrument is not None
    if filled:
        desk.sandbox.place_order(
            OrderRequest(
                instrument=instrument,
                side=Side.SELL,
                quantity=LOT,
                product=Product.MIS,
                order_type=OrderType.MARKET,
                price=None,
                triggered_by="strategy",
                strategy_id=strategy_id,
                run_id=run.id,
            )
        )
    return desk.only_run(strategy_id)


def test_a_signal_entry_the_daemon_lost_is_reconciled(desk: SignalDesk) -> None:
    strategy_id = desk.create()
    _lost_entry(desk, strategy_id, filled=True)

    desk.tick()

    run = desk.only_run(strategy_id)
    assert run.status is RunStatus.OPEN
    assert _legs(run)[-1] == ("leg2.2", Side.SELL, LegStatus.OPEN)
    assert run.legs[-1].risk is not None and run.legs[-1].risk.side is Side.SELL


def test_a_lost_entry_that_never_reached_the_sandbox_leaves_the_run_waiting(
    desk: SignalDesk,
) -> None:
    strategy_id = desk.create()
    _lost_entry(desk, strategy_id, filled=False)

    desk.tick()

    run = desk.only_run(strategy_id)
    assert run.status is RunStatus.OPEN
    assert _legs(run)[-1] == ("leg2.2", Side.SELL, LegStatus.FAILED)


def test_an_alert_for_a_leg_whose_entry_is_unanswered_waits(desk: SignalDesk) -> None:
    strategy_id = desk.create()
    _lost_entry(desk, strategy_id, filled=True)

    # After a restart, commands are carried out before the runs are reconciled.
    again = desk.signal(strategy_id, "leg2", SignalAction.SHORT_ENTRY)

    assert (again.status, again.outcome) == (
        CommandStatus.REFUSED,
        "leg2.2 is pending; send the alert again once it settles",
    )
    assert desk.held() == {CE: LOT, PE: -LOT}


def test_no_entry_while_the_days_run_is_stopping(desk: SignalDesk) -> None:
    strategy_id = desk.create()
    desk.signal(strategy_id, "leg1", SignalAction.LONG_ENTRY)
    desk.market.down_for.add(CE)
    request_stop(strategy_id, "mcp", desk.now)
    process_commands(desk.context, desk.now)

    entry = desk.signal(strategy_id, "leg2", SignalAction.LONG_ENTRY)

    run = desk.only_run(strategy_id)
    assert run.status is RunStatus.STOPPING
    assert (entry.status, entry.outcome) == (CommandStatus.REFUSED, f"run {run.id} is stopping")


def test_a_start_is_refused_for_a_signal_strategy(desk: SignalDesk) -> None:
    strategy_id = desk.create()
    with write_transaction() as session:  # past request_start, which refuses it too
        start = runs_repo.add_command(
            session, strategy_id, CommandKind.START, "mcp", desk.now, broker="fake"
        )

    process_commands(desk.context, desk.now)

    settled = runs_repo.commands_by_id([start.id])[start.id]
    assert (settled.status, settled.outcome) == (
        CommandStatus.REFUSED,
        "a signal strategy enters on its alerts, not on a start",
    )
