"""Start, stop, kill and close legs of a strategy, and read its runs (ADR 21
in docs/adr); give a signal strategy its alert URL and read its alerts (ADR 24
in docs/adr). Nothing here places an order: each request is written as a
command the daemon's runner carries out within about a second, so the MCP
server and the REST API work the same whether or not it is running."""

import ipaddress
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from openticker.core.strategies.models import InvalidStrategyError, SignalStrategySpec
from openticker.core.strategies.runs import Command, CommandKind, CommandStatus, LegStatus, Run
from openticker.storage.sqlite import runs_repo, signals_repo, strategies_repo
from openticker.storage.sqlite.runs_repo import RunEvent, RunOrder
from openticker.storage.sqlite.signals_repo import SignalCall, StoredWebhook
from openticker.storage.sqlite.strategies_repo import StoredStrategy, write_transaction
from openticker.use_cases.strategies.define import StrategyKindError, UnknownStrategyError
from openticker.use_cases.strategies.signals import new_token, token_hash

TIMELINE_LIMIT = 100
MAX_ALLOWED_IPS = 20


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


@dataclass(frozen=True)
class SignalsDetail:
    strategy: StoredStrategy
    webhook: StoredWebhook | None
    calls: list[SignalCall]  # newest first
    commands: dict[int, Command]  # the signal commands they wrote, by id


def request_start(strategy_id: str, broker: str, triggered_by: str, now: datetime) -> Command:
    with write_transaction() as session:
        stored = _strategy(session, strategy_id)
        _refuse_signal_kind(stored, "start")
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
    """Locks the strategy at once, so nothing can start it and its alert URL
    refuses alerts, then closes every open leg. Stays locked until
    `release_kill_switch`."""
    with write_transaction() as session:
        _strategy(session, strategy_id)
        strategies_repo.set_locked(session, strategy_id, True)
        _cancel_pending_starts(
            session, strategy_id, "cancelled by the kill switch", now, CommandKind.SIGNAL
        )
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


def schedule_strategy(strategy_id: str, broker: str) -> StoredStrategy:
    """Enters the strategy at its entry_time on its weekdays, skipping market
    holidays, through `broker`, until `unschedule_strategy`."""
    with write_transaction() as session:
        stored = _strategy(session, strategy_id)
        _refuse_signal_kind(stored, "schedule")
        if stored.spec.schedule.entry_time is None:
            raise StrategyStateError(
                f"{stored.name!r} has no entry_time; set one with update_strategy first"
            )
        if stored.locked:
            raise StrategyLockedError(
                f"{stored.name!r} is locked by its kill switch; release_kill_switch first"
            )
        strategies_repo.set_scheduled(session, strategy_id, broker)
    return strategies_repo.find_strategy(strategy_id) or stored


def unschedule_strategy(strategy_id: str) -> StoredStrategy:
    """No more scheduled entries. A run already open carries on, and its
    exit_time still closes it."""
    with write_transaction() as session:
        stored = _strategy(session, strategy_id)
        strategies_repo.set_scheduled(session, strategy_id, None)
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


def rotate_webhook(
    strategy_id: str, broker: str, allowed_ips: list[str], now: datetime
) -> tuple[StoredStrategy, StoredWebhook, str]:
    """A new alert URL token for a signal strategy; any earlier one stops
    working. The token is returned here and never again: only its hash is
    kept. Alerts' orders are priced through `broker`. A non-empty
    `allowed_ips` (addresses or CIDR ranges) refuses every other caller."""
    if len(allowed_ips) > MAX_ALLOWED_IPS:
        raise InvalidStrategyError(f"at most {MAX_ALLOWED_IPS} allowed addresses or ranges")
    entries = []
    for entry in allowed_ips:
        try:
            entries.append(str(ipaddress.ip_network(entry.strip(), strict=False)))
        except ValueError:
            raise InvalidStrategyError(
                f"{entry!r} is not an IP address or CIDR range, e.g. 52.89.214.238 or 10.0.0.0/8"
            ) from None
    token = new_token()
    with write_transaction() as session:
        stored = _strategy(session, strategy_id)
        if not isinstance(stored.spec, SignalStrategySpec):
            raise StrategyKindError(
                f"{stored.name!r} is an options strategy: it enters on start_strategy or its "
                "schedule, not on alerts; create_signal_strategy makes one alerts drive"
            )
        webhook = signals_repo.set_webhook(
            session, strategy_id, token_hash(token), broker, tuple(entries), now
        )
    return stored, webhook, token


def disable_webhook(strategy_id: str) -> StoredStrategy:
    """Its alert URL stops working. A run already open carries on."""
    with write_transaction() as session:
        stored = _strategy(session, strategy_id)
        if not signals_repo.remove_webhook(session, strategy_id):
            raise StrategyStateError(f"{stored.name!r} has no alert URL; nothing to disable")
    return stored


def get_signals(strategy_id: str, limit: int) -> SignalsDetail:
    stored = strategies_repo.find_strategy(strategy_id)
    if stored is None:
        raise _unknown(strategy_id)
    calls = signals_repo.list_calls(strategy_id, limit)
    return SignalsDetail(
        strategy=stored,
        webhook=signals_repo.find_webhook(strategy_id),
        calls=calls,
        commands=runs_repo.commands_by_id([i for call in calls for i in call.command_ids]),
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


def _refuse_signal_kind(stored: StoredStrategy, doing: str) -> None:
    if isinstance(stored.spec, SignalStrategySpec):
        raise StrategyKindError(
            f"{stored.name!r} is a signal strategy: its alerts enter and exit it, so there is "
            f"nothing to {doing}; rotate_strategy_webhook gives its alert URL"
        )


def _cancel_pending_starts(
    session: Session,
    strategy_id: str,
    why: str,
    now: datetime,
    *also: CommandKind,
) -> bool:
    starts = [
        command
        for command in runs_repo.pending_commands_of(session, strategy_id)
        if command.kind is CommandKind.START or command.kind in also
    ]
    for command in starts:
        runs_repo.settle_command(session, command.id, CommandStatus.REFUSED, why, now)
    return bool(starts)


def _unknown(strategy_id: str) -> UnknownStrategyError:
    return UnknownStrategyError(
        f"no strategy with id {strategy_id!r}; list_strategies shows the ones that exist"
    )
