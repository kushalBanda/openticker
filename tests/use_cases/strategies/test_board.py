from datetime import time, timedelta

from openticker.adapters.sandbox.broker import SandboxSettings
from openticker.core.agents.jobs import AgentJobEndReason, AgentJobKind, Harness
from openticker.core.pnl import DayFigure
from openticker.core.risk.models import StrategyStopReason
from openticker.core.strategies.models import Horizon, Schedule, SignalLeg, SignalStrategySpec
from openticker.core.strategies.runs import CommandKind
from openticker.ports.models import EXCHANGE_TIMEZONE, Exchange
from openticker.storage.sqlite import agent_jobs_repo, runs_repo
from openticker.storage.sqlite.strategies_repo import write_transaction
from openticker.use_cases.strategies.board import Segment, StrategyState, strategy_board
from openticker.use_cases.strategies.control import (
    release_kill_switch,
    request_kill,
    request_start,
    request_stop,
    rotate_webhook,
    schedule_strategy,
)
from openticker.use_cases.strategies.define import create_strategy
from openticker.use_cases.strategies.ledger import get_strategy_ledger
from openticker.use_cases.strategies.runner import process_commands
from tests.fixtures.calendar import NO_HOLIDAYS
from tests.fixtures.strategies import POSITIONAL_STRADDLE, STRADDLE
from tests.fixtures.strategy_desk import CE, Desk

# Real charges from the shipped rates: runs after costs count in the totals.
COSTED = SandboxSettings()

ALERTS = SignalStrategySpec(
    legs=(SignalLeg(symbol=CE, exchange=Exchange.NFO, quantity=65),),
    horizon=Horizon.INTRADAY,
)


def _row(desk: Desk, name: str):  # type: ignore[no-untyped-def]
    [row] = [r for r in strategy_board(NO_HOLIDAYS, desk.now) if r.strategy.name == name]
    return row


def test_a_running_strategy_counts_todays_fills_and_every_run() -> None:
    desk = Desk(COSTED)
    strategy_id = desk.start()
    desk.tick(ce=90.0, pe=95.0)
    request_stop(strategy_id, "mcp", desk.now)
    process_commands(desk.context, desk.now)
    desk.now += timedelta(minutes=5)
    request_start(strategy_id, "fake", "mcp", desk.now)
    process_commands(desk.context, desk.now)

    row = _row(desk, "straddle")

    assert row.state is StrategyState.RUNNING and row.active_run is not None
    assert row.segments == (Segment.OPT,)
    assert (row.runs, row.judged) == (2, 1)
    ledger = get_strategy_ledger(strategy_id, 2)
    assert row.net_pnl == ledger.totals.net_pnl > 0
    # Today holds the ended run and the open one's entry, which paid charges.
    ended, opened = ledger.runs[1], ledger.runs[0]
    assert row.today.gross == ended.gross_pnl > 0
    assert row.today.charges == round(ended.charges + opened.charges, 2) > ended.charges
    assert row.today.net == round(sum(r.net_pnl for r in ledger.runs), 2) < row.net_pnl
    assert row.last_run_at == desk.now


def test_yesterdays_runs_leave_today_at_zero() -> None:
    desk = Desk(COSTED)
    strategy_id = desk.start()
    desk.tick(ce=90.0, pe=95.0)
    request_stop(strategy_id, "mcp", desk.now)
    process_commands(desk.context, desk.now)
    desk.now += timedelta(days=1)

    row = _row(desk, "straddle")

    assert row.state is StrategyState.STOPPED
    assert row.today == DayFigure(0.0, 0.0) and row.net_pnl > 0


def test_a_positional_run_closed_today_counts_today() -> None:
    desk = Desk(COSTED)
    desk.now -= timedelta(days=1)  # the contracts expire today: enter yesterday
    strategy_id = desk.start(POSITIONAL_STRADDLE)
    desk.now += timedelta(days=1)
    desk.tick(ce=90.0, pe=95.0)
    request_stop(strategy_id, "mcp", desk.now)
    process_commands(desk.context, desk.now)

    row = _row(desk, "straddle")

    [run] = get_strategy_ledger(strategy_id, 1).runs
    exits = run.fills[len(run.fills) // 2 :]
    assert row.today.gross == run.gross_pnl > 0  # the whole run closed today
    assert row.today.charges == round(sum(f.charges or 0.0 for f in exits), 2)
    assert 0 < row.today.charges < run.charges  # yesterday's entry charges aren't today's


def test_it_says_how_its_last_run_ended() -> None:
    desk = Desk()
    strategy_id = desk.start()
    assert _row(desk, "straddle").last_end is None
    request_stop(strategy_id, "mcp", desk.now)
    process_commands(desk.context, desk.now)
    desk.now += timedelta(minutes=5)
    request_start(strategy_id, "fake", "mcp", desk.now)
    process_commands(desk.context, desk.now)

    end = _row(desk, "straddle").last_end

    assert end is not None and end.reason is StrategyStopReason.MANUAL
    assert end.at is not None and end.at < desk.now


def test_the_day_used_before_is_what_the_runner_counts_against_the_daily_limit() -> None:
    desk = Desk(COSTED)
    strategy_id = desk.start()
    desk.tick(ce=90.0, pe=95.0)
    request_stop(strategy_id, "mcp", desk.now)
    process_commands(desk.context, desk.now)
    desk.now += timedelta(minutes=5)
    request_start(strategy_id, "fake", "mcp", desk.now)
    process_commands(desk.context, desk.now)

    row = _row(desk, "straddle")

    assert row.active_run is not None
    midnight = desk.now.astimezone(EXCHANGE_TIMEZONE).replace(hour=0, minute=0, second=0)
    runner = runs_repo.realized_since(strategy_id, midnight, row.active_run.id)
    assert row.day_used_before == runner > 0


def test_a_scheduled_strategy_says_when_it_enters_next() -> None:
    desk = Desk()
    spec = STRADDLE.__class__(**{**STRADDLE.__dict__, "schedule": Schedule(entry_time=time(9, 20))})
    stored = create_strategy("weekly", spec, desk.now)
    schedule_strategy(stored.id, "fake")

    row = _row(desk, "weekly")

    local = desk.now.astimezone(EXCHANGE_TIMEZONE)
    assert row.state is StrategyState.SCHEDULED
    assert row.next_entry is not None and row.next_entry > desk.now
    assert row.next_entry.astimezone(EXCHANGE_TIMEZONE).date() == local.date() + timedelta(days=1)


def test_a_start_waiting_for_the_daemon_is_running() -> None:
    desk = Desk()
    stored = create_strategy("waiting", STRADDLE, desk.now)
    request_start(stored.id, "fake", "ui", desk.now)

    row = _row(desk, "waiting")

    assert row.state is StrategyState.RUNNING and row.active_run is None
    assert row.pending is CommandKind.START


def test_a_killed_strategy_is_killed_until_released() -> None:
    desk = Desk()
    strategy_id = desk.start()
    request_kill(strategy_id, "ui", desk.now)

    assert _row(desk, "straddle").state is StrategyState.KILLED
    assert _row(desk, "straddle").pending is CommandKind.KILL

    process_commands(desk.context, desk.now)
    release_kill_switch(strategy_id)
    assert _row(desk, "straddle").state is StrategyState.STOPPED


def test_a_signal_strategy_listens_once_it_has_an_alert_url() -> None:
    desk = Desk()
    stored = create_strategy("alerts", ALERTS, desk.now)

    assert _row(desk, "alerts").state is StrategyState.STOPPED
    assert _row(desk, "alerts").segments == (Segment.OPT,)

    rotate_webhook(stored.id, "fake", [], desk.now)
    assert _row(desk, "alerts").state is StrategyState.LISTENING


def test_the_latest_answered_review_is_kept() -> None:
    desk = Desk()
    stored = create_strategy("reviewed", STRADDLE, desk.now)
    with write_transaction() as session:
        for n, summary in enumerate(("Retire. Net is negative.", "Keep. Net +2,000.", None)):
            job = agent_jobs_repo.add_job(
                session, AgentJobKind.REVIEW, stored.id, Harness.CLAUDE, "ui", desk.now
            )
            agent_jobs_repo.end_job(
                session,
                job.id,
                AgentJobEndReason.FINISHED,
                "exited with code 0",
                desk.now + timedelta(minutes=n),
                summary=summary,
            )

    review = _row(desk, "reviewed").review

    assert review is not None and review.summary == "Keep. Net +2,000."
