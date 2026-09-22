from dataclasses import replace
from datetime import timedelta

import pytest

from openticker.adapters.inbound.daemon.prices import LatestPrices
from openticker.core.orders.models import OrderRequest, OrderResult, OrderType
from openticker.core.risk.models import StrategyLimits, StrategyStopReason
from openticker.core.strategies.models import RiskValue
from openticker.core.strategies.runs import CommandStatus, LegStatus, RunStatus
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
)
from openticker.use_cases.strategies.define import create_strategy
from openticker.use_cases.strategies.runner import (
    EXIT_RETRY,
    START_TIMEOUT,
    process_commands,
    step_runs,
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


def test_an_order_is_recorded_before_it_is_sent(desk: Desk) -> None:
    def crash(request: OrderRequest) -> OrderResult:
        raise RuntimeError("process died mid-order")

    desk.sandbox.place_order = crash  # type: ignore[method-assign]
    stored = create_strategy("straddle", STRADDLE, desk.now)
    request_start(stored.id, "fake", "mcp", desk.now)

    with pytest.raises(RuntimeError):
        process_commands(desk.context, desk.now)

    run = desk.run(stored.id)
    assert [(o.leg_id, o.status) for o in runs_repo.list_orders(run.id)] == [("leg1", "pending")]


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
