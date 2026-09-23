from datetime import timedelta

from openticker.adapters.inbound.daemon.prices import LatestPrices
from openticker.adapters.inbound.daemon.strategy_loop import StrategyLoop
from openticker.core.risk.models import StrategyStopReason
from openticker.core.strategies.runs import RunStatus
from openticker.ports.models import Tick
from openticker.storage.sqlite import runs_repo
from openticker.storage.sqlite.instruments_repo import get_instrument
from openticker.use_cases.strategies.control import request_start
from openticker.use_cases.strategies.define import create_strategy
from tests.fixtures.calendar import NO_HOLIDAYS
from tests.fixtures.strategies import STRADDLE
from tests.fixtures.strategy_desk import CE, PE, Desk


def test_one_pass_starts_a_run_and_the_next_exits_it_on_its_limits() -> None:
    desk = Desk()
    loop = StrategyLoop(
        lambda broker: desk.sandbox,
        desk.prices,
        desk.events,
        lambda: NO_HOLIDAYS,
        None,
        lambda: desk.now,
    )
    stored = create_strategy("straddle", STRADDLE, desk.now)
    request_start(stored.id, "fake", "mcp", desk.now)

    loop.step()
    assert runs_repo.list_runs(stored.id, 1)[0].status is RunStatus.OPEN

    desk.now += timedelta(seconds=1)
    for symbol, price in ((CE, 150.0), (PE, 100.0)):  # every leg priced: -3,250
        desk.market.prices[symbol] = price
        instrument = get_instrument(symbol, "NFO")
        assert instrument is not None
        desk.prices.update([Tick(instrument, price, desk.now)])
    loop.step()

    run = runs_repo.list_runs(stored.id, 1)[0]
    assert run.status is RunStatus.ENDED
    assert run.stop_reason is StrategyStopReason.COMBINED_STOP_LOSS


def test_the_first_pass_notes_runs_left_open_and_quotes_quiet_legs() -> None:
    desk = Desk()
    stored = create_strategy("straddle", STRADDLE, desk.now)
    request_start(stored.id, "fake", "mcp", desk.now)
    StrategyLoop(
        lambda broker: desk.sandbox,
        desk.prices,
        desk.events,
        lambda: NO_HOLIDAYS,
        None,
        lambda: desk.now,
    ).step()

    restarted = LatestPrices()
    loop = StrategyLoop(
        lambda broker: desk.sandbox,
        restarted,
        desk.events,
        lambda: NO_HOLIDAYS,
        None,
        lambda: desk.now,
    )
    desk.now += timedelta(seconds=30)
    loop.step()
    desk.now += timedelta(seconds=10)  # no streamed price since the restart: quoted
    loop.step()

    run = runs_repo.list_runs(stored.id, 1)[0]
    assert run.status is RunStatus.OPEN  # priced by quotes, not stale
    events = [e.message for e in runs_repo.list_events(run.id, 20)]
    assert events.count("openticker-serve started: watching this run again") == 1
    ce = get_instrument(CE, "NFO")
    assert ce is not None and restarted.get(ce) is not None
