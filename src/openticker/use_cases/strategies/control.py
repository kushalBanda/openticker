"""Start, stop, kill and close legs of a strategy, and read its runs (ADR 21
in docs/adr). Nothing here places an order: each request is written as a
command the daemon's runner carries out within about a second, so the MCP
server and the REST API work the same whether or not it is running."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from openticker.core.strategies.runs import Command, CommandKind, CommandStatus, LegStatus, Run
from openticker.storage.sqlite import runs_repo, strategies_repo
from openticker.storage.sqlite.runs_repo import RunEvent, RunOrder
from openticker.storage.sqlite.strategies_repo import StoredStrategy, write_transaction
from openticker.use_cases.strategies.define import UnknownStrategyError

TIMELINE_LIMIT = 100


class StrategyLockedError(Exception):
    """The kill switch is on."""


class StrategyStateError(Exception):
    """The request doesn't fit what the strategy is doing now."""


class UnknownRunError(LookupError):
    pass


@dataclass(frozen=True)
class RunDetail:
    run: Run
    strategy_name: str
    orders: list[RunOrder]
    events: list[RunEvent]


def request_start(strategy_id: str, broker: str, triggered_by: str, now: datetime) -> Command:
    with write_transaction() as session:
        stored = _strategy(session, strategy_id)
        if stored.locked:
            raise StrategyLockedError(
                f"{stored.name!r} is locked by its kill switch; release_kill_switch first"
            )
        _refuse_if_running(session, strategy_id)
        return runs_repo.add_command(
            session, strategy_id, CommandKind.START, triggered_by, now, broker=broker
        )


def request_stop(strategy_id: str, triggered_by: str, now: datetime) -> Command:
    """Closes every open leg and ends the run. A start not carried out yet is
    cancelled instead."""
    with write_transaction() as session:
        stored = _strategy(session, strategy_id)
        cancelled = _cancel_pending_starts(session, strategy_id, "cancelled by a stop", now)
        if runs_repo.active_run_of(session, strategy_id) is None and not cancelled:
            raise StrategyStateError(f"{stored.name!r} is not running; nothing to stop")
        return runs_repo.add_command(session, strategy_id, CommandKind.STOP, triggered_by, now)


def request_kill(strategy_id: str, triggered_by: str, now: datetime) -> Command:
    """Locks the strategy at once, so nothing can start it, then closes every
    open leg. Stays locked until `release_kill_switch`."""
    with write_transaction() as session:
        _strategy(session, strategy_id)
        strategies_repo.set_locked(session, strategy_id, True)
        _cancel_pending_starts(session, strategy_id, "cancelled by the kill switch", now)
        return runs_repo.add_command(session, strategy_id, CommandKind.KILL, triggered_by, now)


def release_kill_switch(strategy_id: str) -> StoredStrategy:
    with write_transaction() as session:
        stored = _strategy(session, strategy_id)
        if any(
            command.kind is CommandKind.KILL
            for command in runs_repo.pending_commands_of(session, strategy_id)
        ):
            raise StrategyStateError(
                "the kill switch is still closing positions; release it once "
                "get_strategy_runs shows the run ended"
            )
        strategies_repo.set_locked(session, strategy_id, False)
    return strategies_repo.find_strategy(strategy_id) or stored


def request_close_leg(strategy_id: str, leg_id: str, triggered_by: str, now: datetime) -> Command:
    """Closes one leg; the run carries on with the rest."""
    with write_transaction() as session:
        stored = _strategy(session, strategy_id)
        run = runs_repo.active_run_of(session, strategy_id)
        if run is None:
            raise StrategyStateError(f"{stored.name!r} is not running; no leg to close")
        leg = next((leg for leg in run.legs if leg.leg_id == leg_id), None)
        if leg is None:
            names = ", ".join(leg.leg_id for leg in run.legs)
            raise StrategyStateError(f"run {run.id} has no {leg_id!r}; its legs are {names}")
        if leg.status is not LegStatus.OPEN:
            raise StrategyStateError(f"{leg_id} is {leg.status}, not open; nothing to close")
        return runs_repo.add_command(
            session, strategy_id, CommandKind.CLOSE_LEG, triggered_by, now, leg_id=leg_id
        )


def get_runs(strategy_id: str, limit: int) -> tuple[StoredStrategy, list[Run], list[Command]]:
    """The strategy, its latest runs and its latest commands, newest first."""
    stored = strategies_repo.find_strategy(strategy_id)
    if stored is None:
        raise _unknown(strategy_id)
    return (
        stored,
        runs_repo.list_runs(strategy_id, limit),
        runs_repo.recent_commands(strategy_id, limit),
    )


def get_run(run_id: str) -> RunDetail:
    run = runs_repo.find_run(run_id)
    if run is None:
        raise UnknownRunError(
            f"no strategy run with id {run_id!r}; get_strategy_runs lists a strategy's runs"
        )
    stored = strategies_repo.find_strategy(run.strategy_id)
    return RunDetail(
        run=run,
        strategy_name=stored.name if stored else run.strategy_id,
        orders=runs_repo.list_orders(run_id),
        events=runs_repo.list_events(run_id, TIMELINE_LIMIT),
    )


def _strategy(session: Session, strategy_id: str) -> StoredStrategy:
    stored = strategies_repo.load_strategy(session, strategy_id)
    if stored is None:
        raise _unknown(strategy_id)
    return stored


def _refuse_if_running(session: Session, strategy_id: str) -> None:
    run = runs_repo.active_run_of(session, strategy_id)
    if run is not None:
        raise StrategyStateError(f"already running as {run.id}; stop_strategy ends it")
    if any(
        command.kind is CommandKind.START
        for command in runs_repo.pending_commands_of(session, strategy_id)
    ):
        raise StrategyStateError("already starting; get_strategy_runs shows when it has")


def _cancel_pending_starts(session: Session, strategy_id: str, why: str, now: datetime) -> bool:
    starts = [
        command
        for command in runs_repo.pending_commands_of(session, strategy_id)
        if command.kind is CommandKind.START
    ]
    for command in starts:
        runs_repo.settle_command(session, command.id, CommandStatus.REFUSED, why, now)
    return bool(starts)


def _unknown(strategy_id: str) -> UnknownStrategyError:
    return UnknownStrategyError(
        f"no strategy with id {strategy_id!r}; list_strategies shows the ones that exist"
    )
