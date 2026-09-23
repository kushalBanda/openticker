from collections.abc import Callable
from dataclasses import replace
from datetime import time, timedelta

import pytest

from openticker.adapters.inbound.daemon.prices import LatestPrices
from openticker.core.orders.models import OrderRequest, OrderResult, OrderType
from openticker.core.risk.models import StrategyLimits, StrategyStopReason
from openticker.core.strategies.models import Horizon, OptionsStrategySpec, RiskValue, Schedule
from openticker.core.strategies.runs import CommandKind, CommandStatus, LegStatus, Run, RunStatus
from openticker.core.strategies.schedule import ENTRY_GRACE
from openticker.events.types import StrategyLegClosed, StrategyStarted, StrategyStopped
from openticker.ports.models import Product, Side, Tick
from openticker.storage.sqlite import runs_repo, strategies_repo
from openticker.storage.sqlite.instruments_repo import get_instrument
from openticker.storage.sqlite.strategies_repo import write_transaction
from openticker.use_cases.strategies.control import (
    request_close_leg,
    request_kill,
    request_start,
    request_stop,
    schedule_strategy,
    unschedule_strategy,
)
from openticker.use_cases.strategies.define import create_strategy
from openticker.use_cases.strategies.runner import (
    EXIT_RETRY,
    START_TIMEOUT,
    process_commands,
    recover_runs,
    start_scheduled,
    step_runs,
    watched_legs,
)
from tests.fixtures.strategies import NOW, STRADDLE
from tests.fixtures.strategy_desk import CE, LOT, PE, Desk


@pytest.fixture
def desk() -> Desk:
    return Desk()


def test_start_enters_every_leg_and_records_the_orders_first(desk: Desk) -> None:
    strategy_id = desk.start()

    run = desk.run(strategy_id)
    assert run.status is RunStatus.OPEN and run.product is Product.MIS
    assert [(leg.symbol, leg.status, leg.entry_price) for leg in run.legs] == [
        (CE, LegStatus.OPEN, 100.0),
        (PE, LegStatus.OPEN, 100.0),
    ]
    assert desk.held() == {CE: -LOT, PE: -LOT}
    orders = runs_repo.list_orders(run.id)
    assert [(o.leg_id, o.intent, o.side, o.status) for o in orders] == [
        ("leg1", "entry", Side.SELL, "FILLED"),
        ("leg2", "entry", Side.SELL, "FILLED"),
    ]
    assert all(o.sandbox_order_id for o in orders)
    started = desk.events.of(StrategyStarted)
    assert len(started) == 1 and CE in started[0].legs  # type: ignore[attr-defined]
    commands = runs_repo.recent_commands(strategy_id, 1)
    assert commands[0].status is CommandStatus.DONE and run.id in (commands[0].outcome or "")


def test_combined_stop_loss_exits_every_leg_and_ends_the_run(desk: Desk) -> None:
    strategy_id = desk.start()

    desk.tick(ce=130.0, pe=100.0)  # -1,950: inside the 3,000 stop
    assert desk.run(strategy_id).status is RunStatus.OPEN
    desk.tick(ce=150.0, pe=100.0)  # -3,250

    run = desk.run(strategy_id)
    assert run.status is RunStatus.ENDED
    assert run.stop_reason is StrategyStopReason.COMBINED_STOP_LOSS
    assert [leg.status for leg in run.legs] == [LegStatus.CLOSED, LegStatus.CLOSED]
    assert run.realized_pnl == -50.0 * LOT
    assert desk.held() == {}
    stopped = desk.events.of(StrategyStopped)
    assert [(s.reason, s.realized_pnl) for s in stopped] == [  # type: ignore[attr-defined]
        ("combined_stop_loss", -50.0 * LOT)
    ]


def test_a_leg_stop_closes_only_that_leg(desk: Desk) -> None:
    guarded = replace(
        STRADDLE,
        legs=(replace(STRADDLE.legs[0], stop_loss=RiskValue(20.0, percent=True)), STRADDLE.legs[1]),
        limits=StrategyLimits(),
    )
    strategy_id = desk.start(guarded)

    desk.tick(ce=121.0, pe=90.0)

    run = desk.run(strategy_id)
    assert run.status is RunStatus.OPEN
    assert [(leg.status, leg.exit_reason) for leg in run.legs] == [
        (LegStatus.CLOSED, "stop_loss"),
        (LegStatus.OPEN, None),
    ]
    assert desk.held() == {PE: -LOT}
    closed = desk.events.of(StrategyLegClosed)
    assert [(c.leg_id, c.realized_pnl) for c in closed] == [  # type: ignore[attr-defined]
        ("leg1", -21.0 * LOT)
    ]


def test_the_run_ends_once_every_leg_exited_on_its_own(desk: Desk) -> None:
    targeted = replace(
        STRADDLE,
        legs=tuple(replace(leg, target=RiskValue(50.0, percent=True)) for leg in STRADDLE.legs),
        limits=StrategyLimits(),
    )
    strategy_id = desk.start(targeted)

    desk.tick(ce=50.0, pe=80.0)
    desk.tick(pe=40.0)

    run = desk.run(strategy_id)
    assert run.status is RunStatus.ENDED and run.stop_reason is StrategyStopReason.LEGS_CLOSED
    assert run.realized_pnl == (50.0 + 60.0) * LOT


def test_prices_from_before_the_entry_are_not_used(desk: Desk) -> None:
    before = desk.now - timedelta(seconds=5)
    for symbol, price in ((CE, 500.0), (PE, 100.0)):  # would breach the combined stop
        instrument = get_instrument(symbol, "NFO")
        assert instrument is not None
        desk.prices.update([Tick(instrument, price, before)])
    strategy_id = desk.start()

    step_runs(desk.context, desk.now + timedelta(seconds=1))

    assert desk.run(strategy_id).status is RunStatus.OPEN


def test_stop_closes_every_leg(desk: Desk) -> None:
    strategy_id = desk.start()
    desk.tick(ce=90.0, pe=95.0)

    request_stop(strategy_id, "mcp", desk.now)
    process_commands(desk.context, desk.now)

    run = desk.run(strategy_id)
    assert run.status is RunStatus.ENDED and run.stop_reason is StrategyStopReason.MANUAL
    assert run.realized_pnl == (10.0 + 5.0) * LOT
    assert desk.held() == {}


def test_kill_flattens_and_stays_locked(desk: Desk) -> None:
    strategy_id = desk.start()

    request_kill(strategy_id, "mcp", desk.now)
    process_commands(desk.context, desk.now)

    run = desk.run(strategy_id)
    assert run.status is RunStatus.ENDED and run.stop_reason is StrategyStopReason.KILL
    assert desk.held() == {}


def test_closing_a_leg_by_hand_never_moves_the_other_stops(desk: Desk) -> None:
    spec = replace(
        STRADDLE,
        legs=tuple(replace(leg, stop_loss=RiskValue(50.0, percent=False)) for leg in STRADDLE.legs),
        limits=StrategyLimits(stops_to_entry_on_leg_stop=True),
    )
    strategy_id = desk.start(spec)
    desk.tick(ce=90.0, pe=80.0)

    request_close_leg(strategy_id, "leg1", "mcp", desk.now)
    process_commands(desk.context, desk.now)
    desk.tick(pe=80.0)

    run = desk.run(strategy_id)
    assert [leg.status for leg in run.legs] == [LegStatus.CLOSED, LegStatus.OPEN]
    assert run.legs[0].exit_reason == "manual"
    assert run.legs[1].risk is not None and run.legs[1].risk.current_sl == 150.0
    assert not run.stops_at_entry


def test_a_leg_stop_moves_the_winning_leg_to_entry(desk: Desk) -> None:
    spec = replace(
        STRADDLE,
        legs=tuple(replace(leg, stop_loss=RiskValue(50.0, percent=False)) for leg in STRADDLE.legs),
        limits=StrategyLimits(combined_stop_loss=3000.0, stops_to_entry_on_leg_stop=True),
    )
    strategy_id = desk.start(spec)

    desk.tick(ce=150.0, pe=80.0)

    run = desk.run(strategy_id)
    assert run.status is RunStatus.OPEN  # the combined stop no longer applies
    assert run.stops_at_entry
    assert run.legs[1].risk is not None and run.legs[1].risk.current_sl == 100.0
    events = [event.message for event in runs_repo.list_events(run.id, 20)]
    assert "stops moved to entry on leg2" in events


def test_a_failed_entry_closes_the_legs_already_entered(desk: Desk) -> None:
    desk.market.day_range = None
    real_place = desk.sandbox.place_order

    def refuse_puts(request: OrderRequest) -> OrderResult:
        if request.instrument.symbol == PE:
            desk.market.down_for.add(PE)
        return real_place(request)

    desk.sandbox.place_order = refuse_puts  # type: ignore[method-assign]
    strategy_id = desk.start()

    run = desk.run(strategy_id)
    assert run.status is RunStatus.ENDED and run.stop_reason is StrategyStopReason.ERROR
    assert "leg2 could not be entered" in (run.stop_detail or "")
    assert [leg.status for leg in run.legs] == [LegStatus.CLOSED, LegStatus.FAILED]
    assert desk.held() == {}
    assert desk.events.of(StrategyStarted) == []


def test_a_start_sent_while_the_daemon_was_down_expires(desk: Desk) -> None:
    stored = create_strategy("straddle", STRADDLE, desk.now)
    request_start(stored.id, "fake", "mcp", desk.now)

    process_commands(desk.context, desk.now + START_TIMEOUT + timedelta(seconds=1))

    command = runs_repo.recent_commands(stored.id, 1)[0]
    assert command.status is CommandStatus.REFUSED and "expired" in (command.outcome or "")
    assert runs_repo.list_runs(stored.id, 1) == []
    assert desk.held() == {}


def test_a_start_after_the_intraday_square_off_is_refused(desk: Desk) -> None:
    desk.now = NOW.replace(hour=9, minute=50)  # 15:20 IST
    stored = create_strategy("straddle", STRADDLE, desk.now)
    request_start(stored.id, "fake", "mcp", desk.now)

    process_commands(desk.context, desk.now)

    command = runs_repo.recent_commands(stored.id, 1)[0]
    assert command.status is CommandStatus.REFUSED and "square-off" in (command.outcome or "")


def test_an_intraday_run_closes_at_the_square_off(desk: Desk) -> None:
    strategy_id = desk.start()

    desk.now = NOW.replace(hour=9, minute=45)  # 15:15 IST
    desk.tick(ce=95.0, pe=95.0)

    run = desk.run(strategy_id)
    assert run.status is RunStatus.ENDED and run.stop_reason is StrategyStopReason.SCHEDULE
    assert desk.held() == {}


def test_an_exit_never_trades_more_than_the_sandbox_holds(desk: Desk) -> None:
    strategy_id = desk.start()
    ce = get_instrument(CE, "NFO")
    assert ce is not None
    desk.sandbox.place_order(
        OrderRequest(ce, Side.BUY, LOT, Product.MIS, OrderType.MARKET, None, "mcp")
    )  # closed by hand, outside the strategy

    request_stop(strategy_id, "mcp", desk.now)
    process_commands(desk.context, desk.now)

    run = desk.run(strategy_id)
    assert run.status is RunStatus.ENDED
    assert desk.held() == {}  # not long the call
    exits = [o for o in runs_repo.list_orders(run.id) if o.intent == "exit"]
    assert [o.leg_id for o in exits] == ["leg2"]


def test_a_failed_exit_is_retried_with_a_growing_pause(desk: Desk) -> None:
    strategy_id = desk.start()
    desk.market.down = True

    request_stop(strategy_id, "mcp", desk.now)
    process_commands(desk.context, desk.now)
    desk.tick()  # too soon: no new attempt
    assert (
        len([o for o in runs_repo.list_orders(desk.run(strategy_id).id) if o.intent == "exit"]) == 2
    )

    desk.tick(seconds=int(EXIT_RETRY.total_seconds()))
    run = desk.run(strategy_id)
    assert [leg.failed_exits for leg in run.legs] == [2, 2]
    assert run.legs[0].retry_at == desk.now + 2 * EXIT_RETRY

    desk.market.down = False
    desk.tick(seconds=int(2 * EXIT_RETRY.total_seconds()))
    assert desk.run(strategy_id).status is RunStatus.ENDED
    assert desk.held() == {}


class _ProcessDied(BaseException):
    """Stands in for the daemon dying: nothing in the runner catches it."""


def test_an_order_is_recorded_before_it_is_sent(desk: Desk) -> None:
    def crash(request: OrderRequest) -> OrderResult:
        raise _ProcessDied

    desk.sandbox.place_order = crash  # type: ignore[method-assign]
    stored = create_strategy("straddle", STRADDLE, desk.now)
    request_start(stored.id, "fake", "mcp", desk.now)

    with pytest.raises(_ProcessDied):
        process_commands(desk.context, desk.now)

    run = desk.run(stored.id)
    assert [(o.leg_id, o.status) for o in runs_repo.list_orders(run.id)] == [("leg1", "pending")]


def test_a_stop_ends_a_run_whose_entry_never_reached_the_sandbox(desk: Desk) -> None:
    real_place = desk.sandbox.place_order

    def crash(request: OrderRequest) -> OrderResult:
        raise _ProcessDied

    desk.sandbox.place_order = crash  # type: ignore[method-assign]
    stored = create_strategy("straddle", STRADDLE, desk.now)
    request_start(stored.id, "fake", "mcp", desk.now)
    with pytest.raises(_ProcessDied):
        process_commands(desk.context, desk.now)
    desk.sandbox.place_order = real_place  # type: ignore[method-assign]

    request_stop(stored.id, "mcp", desk.now)
    process_commands(desk.context, desk.now)

    run = desk.run(stored.id)
    assert run.status is RunStatus.ENDED and run.stop_reason is StrategyStopReason.MANUAL
    assert [leg.status for leg in run.legs] == [LegStatus.FAILED, LegStatus.FAILED]
    assert [(o.leg_id, o.status) for o in runs_repo.list_orders(run.id)] == [("leg1", "not_sent")]
    assert desk.held() == {}

    request_start(stored.id, "fake", "mcp", desk.now)  # no longer blocked
    process_commands(desk.context, desk.now)
    command = runs_repo.recent_commands(stored.id, 1)[0]
    assert command.status is CommandStatus.DONE and "started" in (command.outcome or "")


def test_an_unexpected_error_during_entry_ends_the_run(desk: Desk) -> None:
    real_place = desk.sandbox.place_order

    def break_on_puts(request: OrderRequest) -> OrderResult:
        if request.instrument.symbol == PE:
            raise RuntimeError("database is locked")
        return real_place(request)

    desk.sandbox.place_order = break_on_puts  # type: ignore[method-assign]
    stored = create_strategy("straddle", STRADDLE, desk.now)
    request_start(stored.id, "fake", "mcp", desk.now)

    with pytest.raises(RuntimeError):
        process_commands(desk.context, desk.now)

    run = desk.run(stored.id)
    assert run.status is RunStatus.ENDED and run.stop_reason is StrategyStopReason.ERROR
    assert "database is locked" in (run.stop_detail or "")
    assert [leg.status for leg in run.legs] == [LegStatus.CLOSED, LegStatus.FAILED]
    assert desk.held() == {}


def test_a_fill_the_run_never_recorded_is_picked_up(desk: Desk) -> None:
    real_place = desk.sandbox.place_order

    def die_after_the_put_fills(request: OrderRequest) -> OrderResult:
        result = real_place(request)
        if request.instrument.symbol == PE:
            raise _ProcessDied
        return result

    desk.sandbox.place_order = die_after_the_put_fills  # type: ignore[method-assign]
    stored = create_strategy("straddle", STRADDLE, desk.now)
    request_start(stored.id, "fake", "mcp", desk.now)
    with pytest.raises(_ProcessDied):
        process_commands(desk.context, desk.now)
    desk.sandbox.place_order = real_place  # type: ignore[method-assign]

    desk.tick(ce=100.0, pe=100.0)

    run = desk.run(stored.id)
    assert run.status is RunStatus.OPEN
    assert [(leg.status, leg.entry_price) for leg in run.legs] == [
        (LegStatus.OPEN, 100.0),
        (LegStatus.OPEN, 100.0),
    ]
    assert run.legs[1].risk is not None and run.legs[1].entered_at is not None
    entry = runs_repo.list_orders(run.id)[1]
    assert (entry.leg_id, entry.status, entry.fill_price) == ("leg2", "FILLED", 100.0)
    assert entry.sandbox_order_id

    request_stop(stored.id, "mcp", desk.now)
    process_commands(desk.context, desk.now)
    assert desk.run(stored.id).status is RunStatus.ENDED
    assert desk.held() == {}


def test_a_stop_closes_a_fill_the_run_never_recorded(desk: Desk) -> None:
    real_place = desk.sandbox.place_order

    def die_after_the_put_fills(request: OrderRequest) -> OrderResult:
        result = real_place(request)
        if request.instrument.symbol == PE:
            raise _ProcessDied
        return result

    desk.sandbox.place_order = die_after_the_put_fills  # type: ignore[method-assign]
    stored = create_strategy("straddle", STRADDLE, desk.now)
    request_start(stored.id, "fake", "mcp", desk.now)
    with pytest.raises(_ProcessDied):
        process_commands(desk.context, desk.now)
    desk.sandbox.place_order = real_place  # type: ignore[method-assign]

    request_kill(stored.id, "mcp", desk.now)
    process_commands(desk.context, desk.now)

    run = desk.run(stored.id)
    assert run.status is RunStatus.ENDED and run.stop_reason is StrategyStopReason.KILL
    assert [(leg.status, leg.exit_reason) for leg in run.legs] == [
        (LegStatus.CLOSED, "kill"),
        (LegStatus.CLOSED, "kill"),
    ]
    assert desk.held() == {}


def test_a_fill_on_a_contract_another_leg_holds_is_matched_to_its_own_order(desk: Desk) -> None:
    two_calls = replace(
        STRADDLE, legs=(STRADDLE.legs[0], STRADDLE.legs[0]), limits=StrategyLimits()
    )
    real_place = desk.sandbox.place_order
    placed = 0

    def die_after_the_second_fills(request: OrderRequest) -> OrderResult:
        nonlocal placed
        placed += 1
        desk.market.prices[CE] = 100.0 + placed  # leg1 fills at 101, leg2 at 102
        result = real_place(request)
        if placed == 2:
            raise _ProcessDied
        return result

    desk.sandbox.place_order = die_after_the_second_fills  # type: ignore[method-assign]
    stored = create_strategy("two calls", two_calls, desk.now)
    request_start(stored.id, "fake", "mcp", desk.now)
    with pytest.raises(_ProcessDied):
        process_commands(desk.context, desk.now)
    desk.sandbox.place_order = real_place  # type: ignore[method-assign]

    desk.tick()

    run = desk.run(stored.id)
    assert [(leg.status, leg.entry_price) for leg in run.legs] == [
        (LegStatus.OPEN, 101.0),
        (LegStatus.OPEN, 102.0),
    ]
    first, second = runs_repo.list_orders(run.id)
    assert first.sandbox_order_id != second.sandbox_order_id


def test_a_fill_recorded_but_not_saved_on_the_run_is_picked_up(desk: Desk) -> None:
    real_save = runs_repo.save_run
    saves = 0

    def die_on_the_second_save(run: Run) -> None:
        nonlocal saves
        saves += 1
        if saves == 2:  # leg2's fill, after its order row was settled
            raise _ProcessDied
        real_save(run)

    stored = create_strategy("straddle", STRADDLE, desk.now)
    request_start(stored.id, "fake", "mcp", desk.now)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(runs_repo, "save_run", die_on_the_second_save)
        with pytest.raises(_ProcessDied):
            process_commands(desk.context, desk.now)

    desk.tick()

    run = desk.run(stored.id)
    assert run.status is RunStatus.OPEN
    assert [leg.status for leg in run.legs] == [LegStatus.OPEN, LegStatus.OPEN]
    assert desk.held() == {CE: -LOT, PE: -LOT}


def test_a_run_left_half_entered_stops_and_closes_what_it_holds(desk: Desk) -> None:
    real_place = desk.sandbox.place_order

    def die_before_the_put(request: OrderRequest) -> OrderResult:
        if request.instrument.symbol == PE:
            raise _ProcessDied
        return real_place(request)

    desk.sandbox.place_order = die_before_the_put  # type: ignore[method-assign]
    stored = create_strategy("straddle", STRADDLE, desk.now)
    request_start(stored.id, "fake", "mcp", desk.now)
    with pytest.raises(_ProcessDied):
        process_commands(desk.context, desk.now)
    desk.sandbox.place_order = real_place  # type: ignore[method-assign]

    desk.tick()

    run = desk.run(stored.id)
    assert run.status is RunStatus.ENDED and run.stop_reason is StrategyStopReason.ERROR
    assert "leg2" in (run.stop_detail or "")
    assert [leg.status for leg in run.legs] == [LegStatus.CLOSED, LegStatus.FAILED]
    assert desk.held() == {}


def test_ratchets_are_saved_so_a_restart_carries_on(desk: Desk) -> None:
    trailing = replace(
        STRADDLE,
        legs=(replace(STRADDLE.legs[0], trailing=RiskValue(10.0, percent=False)),),
        limits=StrategyLimits(),
    )
    strategy_id = desk.start(trailing)
    desk.tick(ce=70.0)

    saved = desk.run(strategy_id).legs[0].risk
    assert saved is not None and (saved.current_sl, saved.lowest_price) == (80.0, 70.0)

    desk.prices = LatestPrices()  # a restarted daemon: nothing in memory
    desk.context = replace(desk.context, latest=desk.prices.get)
    desk.tick(ce=80.0)

    run = desk.run(strategy_id)
    assert run.status is RunStatus.ENDED and run.legs[0].exit_price == 80.0


def test_the_daily_loss_limit_counts_earlier_runs_today(desk: Desk) -> None:
    spec = replace(STRADDLE, limits=StrategyLimits(daily_loss_limit=3000.0))
    strategy_id = desk.start(spec)
    desk.tick(ce=130.0)  # -1,950
    request_stop(strategy_id, "mcp", desk.now)
    process_commands(desk.context, desk.now)

    desk.market.prices = {CE: 100.0, PE: 100.0}
    request_start(strategy_id, "fake", "mcp", desk.now)
    process_commands(desk.context, desk.now)
    desk.tick(ce=117.0, pe=100.0)  # -1,105 now, -3,055 today

    run = desk.run(strategy_id)
    assert run.stop_reason is StrategyStopReason.DAILY_LOSS_LIMIT


def test_a_leg_whose_exit_failed_does_not_fire_again(desk: Desk) -> None:
    spec = replace(
        STRADDLE,
        legs=tuple(replace(leg, stop_loss=RiskValue(50.0, percent=False)) for leg in STRADDLE.legs),
        limits=StrategyLimits(stops_to_entry_on_leg_stop=True),
    )
    strategy_id = desk.start(spec)
    desk.market.down_for.add(CE)
    request_close_leg(strategy_id, "leg1", "mcp", desk.now)
    process_commands(desk.context, desk.now)

    desk.tick(ce=160.0, pe=80.0)  # past leg1's stop while its manual exit is retried

    run = desk.run(strategy_id)
    assert [leg.status for leg in run.legs] == [LegStatus.CLOSING, LegStatus.OPEN]
    assert run.legs[0].exit_reason == "manual"
    assert run.legs[1].risk is not None and run.legs[1].risk.current_sl == 150.0
    assert not run.stops_at_entry


def test_a_partial_exit_counts_only_what_this_run_closed(desk: Desk) -> None:
    two_lots = replace(STRADDLE, legs=(replace(STRADDLE.legs[0], lots=2),), limits=StrategyLimits())
    strategy_id = desk.start(two_lots)
    ce = get_instrument(CE, "NFO")
    assert ce is not None
    desk.sandbox.place_order(
        OrderRequest(ce, Side.BUY, LOT, Product.MIS, OrderType.MARKET, None, "mcp")
    )

    desk.market.prices[CE] = 90.0
    request_stop(strategy_id, "mcp", desk.now)
    process_commands(desk.context, desk.now)

    run = desk.run(strategy_id)
    assert (run.legs[0].quantity, run.legs[0].exit_price) == (LOT, 90.0)
    assert run.realized_pnl == 10.0 * LOT
    assert desk.held() == {}


def test_a_start_is_refused_if_the_strategy_got_locked_meanwhile(desk: Desk) -> None:
    stored = create_strategy("straddle", STRADDLE, desk.now)
    request_start(stored.id, "fake", "mcp", desk.now)
    with write_transaction() as session:
        strategies_repo.set_locked(session, stored.id, True)

    process_commands(desk.context, desk.now)

    command = runs_repo.recent_commands(stored.id, 1)[0]
    assert command.status is CommandStatus.REFUSED and "kill switch" in (command.outcome or "")
    assert desk.held() == {}


# Schedule (ADR 22)

ENTRY_AT = NOW - timedelta(minutes=10)  # 09:20 IST, STRADDLE's entry_time
POSITIONAL = replace(STRADDLE, horizon=Horizon.POSITIONAL, limits=StrategyLimits())


def _scheduled(desk: Desk, spec: OptionsStrategySpec = STRADDLE) -> str:
    stored = create_strategy("scheduled", spec, desk.now)
    schedule_strategy(stored.id, "fake")
    return stored.id


def _pass(desk: Desk) -> None:
    start_scheduled(desk.context, desk.now)
    process_commands(desk.context, desk.now)


def test_a_scheduled_strategy_enters_once_at_its_entry_time(desk: Desk) -> None:
    desk.now = ENTRY_AT - timedelta(seconds=1)
    strategy_id = _scheduled(desk)
    _pass(desk)
    assert runs_repo.recent_commands(strategy_id, 5) == []

    desk.now = ENTRY_AT
    _pass(desk)
    desk.now += timedelta(seconds=30)
    _pass(desk)

    commands = runs_repo.recent_commands(strategy_id, 5)
    assert [(c.triggered_by, c.status) for c in commands] == [("schedule", CommandStatus.DONE)]
    run = desk.run(strategy_id)
    assert run.status is RunStatus.OPEN and run.trigger == "schedule"
    assert desk.held() == {CE: -LOT, PE: -LOT}


def test_a_scheduled_strategy_enters_again_the_next_day(desk: Desk) -> None:
    desk.now = ENTRY_AT - timedelta(days=1)
    strategy_id = _scheduled(desk)
    _pass(desk)
    request_stop(strategy_id, "mcp", desk.now)
    process_commands(desk.context, desk.now)

    desk.now = ENTRY_AT
    _pass(desk)

    starts = [c for c in runs_repo.recent_commands(strategy_id, 5) if c.kind is CommandKind.START]
    assert [(c.triggered_by, c.status) for c in starts] == [("schedule", CommandStatus.DONE)] * 2
    assert desk.run(strategy_id).status is RunStatus.OPEN


def test_a_strategy_not_scheduled_waits_for_start_strategy(desk: Desk) -> None:
    desk.now = ENTRY_AT
    stored = create_strategy("manual", STRADDLE, desk.now)

    _pass(desk)

    assert runs_repo.recent_commands(stored.id, 5) == []
    strategy_id = _scheduled(desk, replace(STRADDLE, legs=STRADDLE.legs[:1]))
    unschedule_strategy(strategy_id)
    _pass(desk)
    assert runs_repo.recent_commands(strategy_id, 5) == []


def test_an_entry_missed_while_the_daemon_was_down_is_skipped(desk: Desk) -> None:
    desk.now = ENTRY_AT + ENTRY_GRACE
    strategy_id = _scheduled(desk)

    _pass(desk)

    assert runs_repo.recent_commands(strategy_id, 5) == []


def test_a_scheduled_start_of_a_running_strategy_is_refused_and_recorded(desk: Desk) -> None:
    desk.now = ENTRY_AT
    strategy_id = _scheduled(desk)
    request_start(strategy_id, "fake", "mcp", desk.now)  # by hand, at the entry time
    process_commands(desk.context, desk.now)

    desk.now += timedelta(seconds=1)
    _pass(desk)

    command = runs_repo.recent_commands(strategy_id, 1)[0]
    assert command.triggered_by == "schedule" and command.status is CommandStatus.REFUSED
    assert command.outcome == "already running"


def test_a_killed_strategy_is_not_entered_by_its_schedule(desk: Desk) -> None:
    desk.now = ENTRY_AT - timedelta(seconds=30)
    strategy_id = _scheduled(desk)
    request_kill(strategy_id, "mcp", desk.now)
    process_commands(desk.context, desk.now)

    desk.now = ENTRY_AT
    _pass(desk)

    command = runs_repo.recent_commands(strategy_id, 1)[0]
    assert command.status is CommandStatus.REFUSED and "kill switch" in (command.outcome or "")
    assert desk.held() == {}


def test_exit_time_closes_a_positional_run(desk: Desk) -> None:
    spec = replace(POSITIONAL, schedule=Schedule(exit_time=time(14, 0), exit_on_expiry=False))
    strategy_id = desk.start(spec)

    desk.now = NOW.replace(hour=8, minute=29)  # 13:59 IST
    desk.tick(ce=100.0, pe=100.0)
    assert desk.run(strategy_id).status is RunStatus.OPEN
    desk.tick(seconds=60, ce=90.0, pe=90.0)

    run = desk.run(strategy_id)
    assert run.status is RunStatus.ENDED and run.stop_reason is StrategyStopReason.SCHEDULE
    assert run.stop_detail == "exit_time 14:00"
    assert desk.held() == {}


def test_a_positional_run_closes_on_its_contracts_expiry_day(desk: Desk) -> None:
    strategy_id = desk.start(replace(POSITIONAL, schedule=Schedule()))

    desk.now = NOW.replace(hour=9, minute=45)  # 15:15 IST on the weekly expiry
    desk.tick(ce=100.0, pe=100.0)

    run = desk.run(strategy_id)
    assert run.status is RunStatus.ENDED and run.stop_reason is StrategyStopReason.EXPIRY
    assert desk.held() == {}


def test_a_start_its_schedule_would_close_at_once_is_refused(desk: Desk) -> None:
    desk.now = NOW.replace(hour=9, minute=46)  # 15:16 IST on the weekly expiry
    stored = create_strategy("late", replace(POSITIONAL, schedule=Schedule()), desk.now)
    request_start(stored.id, "fake", "mcp", desk.now)

    process_commands(desk.context, desk.now)

    command = runs_repo.recent_commands(stored.id, 1)[0]
    assert command.status is CommandStatus.REFUSED
    assert command.outcome == "its schedule would close it at once (expiry day exit 15:15)"
    assert desk.held() == {}


# Lost prices and recovery (ADR 23)


def _quote(desk: Desk, **prices: float) -> None:
    """Moves prices as fetched quotes, not the stream."""
    for symbol, price in {CE: prices.get("ce"), PE: prices.get("pe")}.items():
        if price is None:
            continue
        desk.market.prices[symbol] = price
        instrument = get_instrument(symbol, "NFO")
        assert instrument is not None
        desk.prices.update_polled([Tick(instrument, price, desk.now)])


def test_a_minute_without_any_price_stops_the_run_and_closes_every_leg(desk: Desk) -> None:
    strategy_id = desk.start()

    desk.tick(seconds=59)
    assert desk.run(strategy_id).status is RunStatus.OPEN
    desk.tick(seconds=1)

    run = desk.run(strategy_id)
    assert run.status is RunStatus.ENDED and run.stop_reason is StrategyStopReason.TICK_STALE
    assert run.stop_detail == f"no price, streamed or quoted, for 60s: {CE}, {PE}"
    exits = [o.leg_id for o in runs_repo.list_orders(run.id) if o.intent == "exit"]
    assert exits == ["leg1", "leg2"]
    assert desk.held() == {}
    stopped = desk.events.of(StrategyStopped)
    assert [s.reason for s in stopped] == ["tick_stale"]  # type: ignore[attr-defined]


def test_one_leg_going_stale_stops_the_run(desk: Desk) -> None:
    strategy_id = desk.start()

    for _ in range(6):
        desk.tick(seconds=10, ce=100.0)  # the put is never priced

    run = desk.run(strategy_id)
    assert run.stop_reason is StrategyStopReason.TICK_STALE
    assert run.stop_detail == f"no price, streamed or quoted, for 60s: {PE}"


def test_quotes_keep_an_illiquid_leg_from_going_stale(desk: Desk) -> None:
    strategy_id = desk.start()

    for _ in range(18):  # three minutes with no stream at all
        desk.now += timedelta(seconds=10)
        _quote(desk, ce=100.0, pe=100.0)
        step_runs(desk.context, desk.now)

    assert desk.run(strategy_id).status is RunStatus.OPEN


def test_a_run_stopped_for_stale_prices_does_not_resume(desk: Desk) -> None:
    strategy_id = desk.start()
    desk.tick(seconds=60)

    desk.tick(ce=100.0, pe=100.0)
    desk.tick(ce=100.0, pe=100.0)

    runs = runs_repo.list_runs(strategy_id, 5)
    assert [run.status for run in runs] == [RunStatus.ENDED]
    assert runs_repo.recent_commands(strategy_id, 1)[0].kind is CommandKind.START
    assert desk.held() == {}


def test_prices_are_not_expected_while_the_market_is_shut(desk: Desk) -> None:
    strategy_id = desk.start(
        replace(STRADDLE, horizon=Horizon.POSITIONAL, schedule=Schedule(exit_on_expiry=False))
    )
    desk.tick(ce=100.0, pe=100.0)

    desk.now = NOW.replace(hour=11, minute=0)  # 16:30 IST, after the close
    step_runs(desk.context, desk.now)
    desk.now = NOW.replace(day=23, hour=3, minute=45, second=59)  # 09:15:59 IST next day
    step_runs(desk.context, desk.now)
    assert desk.run(strategy_id).status is RunStatus.OPEN

    desk.now += timedelta(seconds=1)  # a minute into the session with no price
    step_runs(desk.context, desk.now)
    assert desk.run(strategy_id).stop_reason is StrategyStopReason.TICK_STALE


def test_the_run_records_its_lowest_pnl(desk: Desk) -> None:
    strategy_id = desk.start(replace(STRADDLE, limits=StrategyLimits()))

    desk.tick(ce=120.0, pe=100.0)  # -1,300
    desk.tick(ce=90.0, pe=100.0)  # +650

    run = desk.run(strategy_id)
    assert (run.trough_mtm, run.peak_mtm) == (-20.0 * LOT, 10.0 * LOT)


def _die_during_exits(desk: Desk, after_fill: bool) -> Callable[[OrderRequest], OrderResult]:
    """Makes the process die on the straddle's exits; returns the real placement."""
    real_place = desk.sandbox.place_order

    def die(request: OrderRequest) -> OrderResult:
        if request.side is Side.BUY:  # the straddle's exits
            if after_fill:
                real_place(request)
            raise _ProcessDied
        return real_place(request)

    desk.sandbox.place_order = die  # type: ignore[method-assign]
    return real_place


def test_an_exit_filled_but_never_recorded_closes_the_leg_at_its_fill(desk: Desk) -> None:
    strategy_id = desk.start()
    real_place = _die_during_exits(desk, after_fill=True)
    desk.market.prices[CE] = 90.0
    request_stop(strategy_id, "mcp", desk.now)
    with pytest.raises(_ProcessDied):
        process_commands(desk.context, desk.now)
    desk.sandbox.place_order = real_place  # type: ignore[method-assign,assignment]
    desk.market.prices[CE] = 95.0  # where a blind exit would now fill

    desk.tick(seconds=1)

    run = desk.run(strategy_id)
    assert run.status is RunStatus.ENDED and run.stop_reason is StrategyStopReason.MANUAL
    assert [(leg.status, leg.exit_price) for leg in run.legs] == [
        (LegStatus.CLOSED, 90.0),
        (LegStatus.CLOSED, 100.0),
    ]
    exits = [o for o in runs_repo.list_orders(run.id) if o.intent == "exit"]
    assert [(o.leg_id, o.status) for o in exits] == [("leg1", "FILLED"), ("leg2", "FILLED")]
    assert desk.held() == {}


def test_an_exit_that_never_reached_the_sandbox_is_sent_again(desk: Desk) -> None:
    strategy_id = desk.start()
    real_place = _die_during_exits(desk, after_fill=False)
    request_stop(strategy_id, "mcp", desk.now)
    with pytest.raises(_ProcessDied):
        process_commands(desk.context, desk.now)
    desk.sandbox.place_order = real_place  # type: ignore[method-assign,assignment]

    desk.tick(seconds=1)

    run = desk.run(strategy_id)
    assert run.status is RunStatus.ENDED
    exits = [(o.leg_id, o.status) for o in runs_repo.list_orders(run.id) if o.intent == "exit"]
    assert exits == [("leg1", "not_sent"), ("leg1", "FILLED"), ("leg2", "FILLED")]
    assert desk.held() == {}


def test_an_exit_filled_and_recorded_but_not_saved_on_the_run_is_taken_in(desk: Desk) -> None:
    strategy_id = desk.start()
    desk.market.prices[CE] = 90.0
    real_save = runs_repo.save_run

    def die_saving_a_closed_leg(run: Run) -> None:
        if any(leg.status is LegStatus.CLOSED for leg in run.legs):
            raise _ProcessDied
        real_save(run)

    request_stop(strategy_id, "mcp", desk.now)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(runs_repo, "save_run", die_saving_a_closed_leg)
        with pytest.raises(_ProcessDied):
            process_commands(desk.context, desk.now)
    desk.market.prices[CE] = 95.0

    desk.tick(seconds=1)

    run = desk.run(strategy_id)
    assert run.status is RunStatus.ENDED
    assert run.legs[0].exit_price == 90.0
    assert len([o for o in runs_repo.list_orders(run.id) if o.intent == "exit"]) == 2


def test_orders_the_sandbox_cannot_account_for_stop_the_run_recovery_failed(desk: Desk) -> None:
    strategy_id = desk.start()
    run = desk.run(strategy_id)
    runs_repo.save_run(_with_closing(run))
    order_id = runs_repo.add_order(run.id, run.legs[0], "exit", Side.BUY, LOT, desk.now)
    runs_repo.settle_order(order_id, "pending", "sb_missing", None, None, desk.now)

    desk.tick(seconds=1)

    run = desk.run(strategy_id)
    assert run.status is RunStatus.ENDED and run.stop_reason is StrategyStopReason.RECOVERY_FAILED
    assert "sb_missing is not in the sandbox" in (run.stop_detail or "")
    assert desk.held() == {}  # what the sandbox held was closed
    statuses = [o.status for o in runs_repo.list_orders(run.id) if o.intent == "exit"]
    assert statuses[0] == "unreconciled"


def _with_closing(run: Run) -> Run:
    leg = replace(run.legs[0], status=LegStatus.CLOSING, exit_reason="manual")
    return replace(run, legs=(leg, *run.legs[1:]))


def test_a_restarted_daemon_notes_each_open_run_and_carries_on_without_reentering(
    desk: Desk,
) -> None:
    strategy_id = desk.start()
    entries = len(runs_repo.list_orders(desk.run(strategy_id).id))

    desk.prices = LatestPrices()  # a restarted daemon: nothing in memory
    desk.context = replace(desk.context, latest=desk.prices.get)
    assert recover_runs(desk.context, desk.now) == 1
    desk.tick(ce=100.0, pe=100.0)

    run = desk.run(strategy_id)
    assert run.status is RunStatus.OPEN
    assert len(runs_repo.list_orders(run.id)) == entries
    events = [event.message for event in runs_repo.list_events(run.id, 20)]
    assert "openticker-serve started: watching this run again" in events


def test_a_partial_exit_never_recorded_counts_only_what_it_closed(desk: Desk) -> None:
    two_lots = replace(STRADDLE, legs=(replace(STRADDLE.legs[0], lots=2),), limits=StrategyLimits())
    strategy_id = desk.start(two_lots)
    ce = get_instrument(CE, "NFO")
    assert ce is not None
    desk.sandbox.place_order(
        OrderRequest(ce, Side.BUY, LOT, Product.MIS, OrderType.MARKET, None, "mcp")
    )  # one lot closed by hand
    real_place = _die_during_exits(desk, after_fill=True)
    desk.market.prices[CE] = 90.0
    request_stop(strategy_id, "mcp", desk.now)
    with pytest.raises(_ProcessDied):
        process_commands(desk.context, desk.now)
    desk.sandbox.place_order = real_place  # type: ignore[method-assign,assignment]

    desk.tick(seconds=1)

    run = desk.run(strategy_id)
    assert (run.legs[0].quantity, run.legs[0].exit_price) == (LOT, 90.0)
    assert run.realized_pnl == 10.0 * LOT


def test_an_entry_the_sandbox_cannot_account_for_is_closed_as_if_held(desk: Desk) -> None:
    strategy_id = desk.start()
    run = desk.run(strategy_id)
    pending = replace(run.legs[1], status=LegStatus.PENDING, entry_price=None, risk=None)
    runs_repo.save_run(replace(run, legs=(run.legs[0], pending)))
    entry = next(o for o in runs_repo.list_orders(run.id) if o.leg_id == "leg2")
    runs_repo.settle_order(entry.id, "pending", "sb_missing", None, None, desk.now)

    desk.tick(seconds=1)

    run = desk.run(strategy_id)
    assert run.status is RunStatus.ENDED and run.stop_reason is StrategyStopReason.RECOVERY_FAILED
    assert run.legs[1].exit_reason == "recovery_failed"
    assert desk.held() == {}


def test_watched_legs_are_the_held_contracts_while_their_market_is_open(desk: Desk) -> None:
    guarded = replace(
        STRADDLE,
        legs=(replace(STRADDLE.legs[0], stop_loss=RiskValue(20.0, percent=True)), STRADDLE.legs[1]),
        limits=StrategyLimits(),
    )
    strategy_id = desk.start(guarded)
    entered = desk.run(strategy_id).legs[0].entered_at
    desk.tick(ce=121.0, pe=90.0)  # leg1 stopped out

    watched = watched_legs(desk.context, desk.now)
    assert [(w.broker, w.instrument.symbol, w.since) for w in watched] == [("fake", PE, entered)]
    assert watched_legs(desk.context, NOW.replace(hour=10, minute=1)) == []  # 15:31 IST


def test_a_restart_long_after_the_entry_is_not_stale_at_once(desk: Desk) -> None:
    strategy_id = desk.start()
    desk.now += timedelta(minutes=90)  # the daemon was down; nothing priced since
    desk.prices = LatestPrices()
    desk.context = replace(desk.context, latest=desk.prices.get, watching_from=desk.now)

    step_runs(desk.context, desk.now)
    assert desk.run(strategy_id).status is RunStatus.OPEN
    desk.now += timedelta(seconds=60)  # a full minute after the restart, still nothing
    step_runs(desk.context, desk.now)
    assert desk.run(strategy_id).stop_reason is StrategyStopReason.TICK_STALE
