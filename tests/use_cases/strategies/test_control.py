import pytest

from openticker.core.strategies.runs import CommandKind, CommandStatus, LegStatus
from openticker.storage.sqlite import runs_repo
from openticker.use_cases.strategies.control import (
    StrategyLockedError,
    StrategyStateError,
    UnknownRunError,
    get_run,
    release_kill_switch,
    request_close_leg,
    request_kill,
    request_start,
    request_stop,
)
from openticker.use_cases.strategies.define import (
    StrategyRunningError,
    UnknownStrategyError,
    create_strategy,
    delete_strategy,
    get_strategy,
    update_strategy,
)
from openticker.use_cases.strategies.runner import process_commands
from tests.fixtures.strategies import NOW, STRADDLE, list_nifty_market
from tests.fixtures.strategy_desk import Desk


@pytest.fixture(autouse=True)
def _market() -> None:
    list_nifty_market()


def test_start_is_queued_for_the_daemon() -> None:
    stored = create_strategy("straddle", STRADDLE, NOW)

    command = request_start(stored.id, "zerodha", "mcp", NOW)

    assert (command.kind, command.status, command.broker) == (
        CommandKind.START,
        CommandStatus.PENDING,
        "zerodha",
    )


def test_a_second_start_is_refused_while_the_first_is_pending() -> None:
    stored = create_strategy("straddle", STRADDLE, NOW)
    request_start(stored.id, "zerodha", "mcp", NOW)

    with pytest.raises(StrategyStateError, match="already starting"):
        request_start(stored.id, "zerodha", "mcp", NOW)


def test_start_is_refused_while_a_run_is_open() -> None:
    desk = Desk()
    strategy_id = desk.start()

    with pytest.raises(StrategyStateError, match="already running"):
        request_start(strategy_id, "fake", "mcp", NOW)


def test_stop_cancels_a_start_not_carried_out_yet() -> None:
    stored = create_strategy("straddle", STRADDLE, NOW)
    start = request_start(stored.id, "zerodha", "mcp", NOW)

    request_stop(stored.id, "mcp", NOW)

    commands = {c.id: c for c in runs_repo.recent_commands(stored.id, 5)}
    assert commands[start.id].status is CommandStatus.REFUSED
    assert "cancelled by a stop" in (commands[start.id].outcome or "")


def test_stop_refuses_when_nothing_is_running() -> None:
    stored = create_strategy("straddle", STRADDLE, NOW)

    with pytest.raises(StrategyStateError, match="not running"):
        request_stop(stored.id, "mcp", NOW)


def test_kill_locks_at_once_and_cancels_a_pending_start() -> None:
    stored = create_strategy("straddle", STRADDLE, NOW)
    request_start(stored.id, "zerodha", "mcp", NOW)

    request_kill(stored.id, "mcp", NOW)

    assert get_strategy(stored.id).locked
    assert [c.kind for c in runs_repo.recent_commands(stored.id, 5) if c.status == "pending"] == [
        CommandKind.KILL
    ]
    with pytest.raises(StrategyLockedError, match="release_kill_switch"):
        request_start(stored.id, "zerodha", "mcp", NOW)


def test_release_waits_for_the_kill_to_finish() -> None:
    desk = Desk()
    strategy_id = desk.start()
    request_kill(strategy_id, "mcp", desk.now)

    with pytest.raises(StrategyStateError, match="still closing"):
        release_kill_switch(strategy_id)

    process_commands(desk.context, desk.now)
    assert not release_kill_switch(strategy_id).locked
    request_start(strategy_id, "fake", "mcp", desk.now)


def test_close_leg_checks_the_leg() -> None:
    desk = Desk()
    strategy_id = desk.start()

    with pytest.raises(StrategyStateError, match="its legs are leg1, leg2"):
        request_close_leg(strategy_id, "leg9", "mcp", desk.now)
    request_close_leg(strategy_id, "leg1", "mcp", desk.now)
    process_commands(desk.context, desk.now)
    with pytest.raises(StrategyStateError, match="closed, not open"):
        request_close_leg(strategy_id, "leg1", "mcp", desk.now)


def test_close_leg_refuses_when_nothing_is_running() -> None:
    stored = create_strategy("straddle", STRADDLE, NOW)

    with pytest.raises(StrategyStateError, match="not running"):
        request_close_leg(stored.id, "leg1", "mcp", NOW)


def test_a_running_strategy_is_not_edited_or_deleted() -> None:
    desk = Desk()
    strategy_id = desk.start()

    with pytest.raises(StrategyRunningError, match="stop the strategy before editing"):
        update_strategy(strategy_id, "renamed", STRADDLE, desk.now)
    with pytest.raises(StrategyRunningError, match="stop the strategy before deleting"):
        delete_strategy(strategy_id, desk.now)

    request_stop(strategy_id, "mcp", desk.now)
    process_commands(desk.context, desk.now)
    assert update_strategy(strategy_id, "renamed", STRADDLE, desk.now).name == "renamed"


def test_a_strategy_about_to_start_is_not_edited() -> None:
    stored = create_strategy("straddle", STRADDLE, NOW)
    request_start(stored.id, "zerodha", "mcp", NOW)

    with pytest.raises(StrategyRunningError):
        update_strategy(stored.id, "renamed", STRADDLE, NOW)


def test_get_run_gives_legs_orders_and_timeline() -> None:
    desk = Desk()
    strategy_id = desk.start()
    run_id = runs_repo.list_runs(strategy_id, 1)[0].id

    detail = get_run(run_id)

    assert detail.strategy_name == "straddle"
    assert [leg.status for leg in detail.run.legs] == [LegStatus.OPEN, LegStatus.OPEN]
    assert len(detail.orders) == 2
    assert detail.events[0].message.startswith("started by mcp: leg1 ATM NIFTY22SEP262500CE")
    with pytest.raises(UnknownRunError):
        get_run("run_nope")


def test_commands_on_an_unknown_strategy_say_so() -> None:
    with pytest.raises(UnknownStrategyError, match="list_strategies"):
        request_kill("stg_nope", "mcp", NOW)
