"""The strategy runner, called only by the daemon (ADR 21 in docs/adr).

`start_scheduled` writes the starts a strategy's schedule asks for (ADR 22 in
docs/adr). `process_commands` carries out what the MCP server, the REST API,
the schedule and alerts asked for: start, stop, kill, close a leg, and a
signal strategy's entries and exits (ADR 24 in docs/adr). `step_runs` judges
every open run at the latest live prices, each leg on its own rules and the
whole run on the strategy's (ADR 19), and closes what those rules and the
schedule say to close.

Every order is recorded in `strategy_orders` before it is sent. A run's legs,
ratchets and stop reason are saved as they change, so a restarted daemon
carries on watching them.
"""

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from openticker.core.calendar.calendar import intraday_allowed, market_status, session_hours
from openticker.core.calendar.models import MarketCalendar
from openticker.core.orders.models import (
    Order,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
)
from openticker.core.risk.aggregate import evaluate_strategy
from openticker.core.risk.models import (
    LegState,
    PositionRisk,
    StrategyLimits,
    StrategyRisk,
    StrategyStopReason,
)
from openticker.core.strategies.models import (
    LegSpec,
    OptionsStrategySpec,
    SignalLeg,
    SignalStrategySpec,
    leg_id,
)
from openticker.core.strategies.prices import PriceTimeouts, is_stale, watched_since
from openticker.core.strategies.runs import (
    Command,
    CommandKind,
    CommandStatus,
    LegStatus,
    Run,
    RunLeg,
    RunStatus,
    leg_risk,
    product_for,
)
from openticker.core.strategies.schedule import entry_due, exit_due
from openticker.core.strategies.signals import Move, signal_move
from openticker.events.bus import EventPublisher
from openticker.events.types import StrategyLegClosed, StrategyStarted, StrategyStopped
from openticker.ports.models import EXCHANGE_TIMEZONE, Exchange, Instrument, Product, Side, Tick
from openticker.ports.sandbox_port import OrderSandbox
from openticker.storage.sqlite import runs_repo, strategies_repo
from openticker.storage.sqlite.instruments_repo import get_instrument
from openticker.storage.sqlite.runs_repo import SCHEDULE_TRIGGER, WEBHOOK_TRIGGER, RunOrder
from openticker.storage.sqlite.strategies_repo import StoredStrategy, write_transaction
from openticker.use_cases.place_order import place_order
from openticker.use_cases.strategies.define import resolve_legs

# A start the daemon finds older than this was sent while it wasn't running;
# entering minutes or hours later, at other prices, is not what was asked.
START_TIMEOUT = timedelta(seconds=60)
# A failed exit is tried again after 30 seconds, then twice as long after each
# further failure, up to 10 minutes: every attempt that fails is notified.
EXIT_RETRY = timedelta(seconds=30)
EXIT_RETRY_MAX = timedelta(minutes=10)
COMMANDS_PER_PASS = 20


@dataclass(frozen=True)
class RunnerContext:
    """What every runner call needs from the daemon."""

    sandbox: Callable[[str], OrderSandbox]  # by broker name
    latest: Callable[[Instrument], Tick | None]
    events: EventPublisher
    calendar: MarketCalendar
    capital_cap: float | None
    timeouts: PriceTimeouts = field(default_factory=PriceTimeouts)
    watching_from: datetime | None = None  # when the daemon started: no price is held from before


@dataclass(frozen=True)
class WatchedLeg:
    """A contract an open run holds, and since when its price is expected."""

    broker: str
    instrument: Instrument
    since: datetime


def recover_runs(context: RunnerContext, now: datetime) -> int:
    """On the daemon's start: notes on every run not yet ended that it is
    watched again. Each is reconciled with the sandbox at its first step,
    before anything else is decided (ADR 14 and ADR 23 in docs/adr)."""
    runs = runs_repo.active_runs()
    for run in runs:
        runs_repo.add_event(run.id, now, "openticker-serve started: watching this run again")
    return len(runs)


def watched_legs(context: RunnerContext, now: datetime) -> list[WatchedLeg]:
    """The contracts open runs hold, while their market is in session: what
    needs a price, streamed or fetched (ADR 23 in docs/adr)."""
    watched: list[WatchedLeg] = []
    for run in runs_repo.active_runs():
        for leg in run.legs:
            if not leg.is_open:
                continue
            opens = _session_opened(leg.exchange, context.calendar, now)
            instrument = get_instrument(leg.symbol, leg.exchange.value)
            if opens is None or instrument is None:
                continue
            watched.append(
                WatchedLeg(
                    run.broker,
                    instrument,
                    watched_since(leg.entered_at, opens, context.watching_from),
                )
            )
    return watched


def _session_opened(exchange: Exchange, calendar: MarketCalendar, now: datetime) -> datetime | None:
    """When today's session opened, while it is open."""
    hours = session_hours(now.astimezone(EXCHANGE_TIMEZONE).date(), exchange, calendar)
    if hours is None or not hours.opens_at <= now < hours.closes_at:
        return None
    return hours.opens_at


def start_scheduled(context: RunnerContext, now: datetime) -> None:
    """Writes a start for every scheduled strategy whose entry is due. Once
    per entry: whatever becomes of it (a refusal, a strategy already running)
    is the command's answer, carried out with the other commands."""
    for stored in strategies_repo.list_scheduled():
        if not isinstance(stored.spec, OptionsStrategySpec):
            continue
        due = entry_due(stored.spec.schedule, stored.spec.exchange, context.calendar, now)
        if due is None:
            continue
        with write_transaction() as session:
            if runs_repo.scheduled_start_since(session, stored.id, due):
                continue
            runs_repo.add_command(
                session,
                stored.id,
                CommandKind.START,
                SCHEDULE_TRIGGER,
                now,
                broker=stored.scheduled_broker,
            )


def process_commands(context: RunnerContext, now: datetime) -> None:
    for _ in range(COMMANDS_PER_PASS):
        command = runs_repo.next_pending_command()
        if command is None:
            return
        _carry_out(context, command, now)


def step_runs(context: RunnerContext, now: datetime) -> None:
    """One pass over every run not yet ended. A run that fails doesn't hold up
    the others; the failures are raised together at the end."""
    failures: list[Exception] = []
    for run in runs_repo.active_runs():
        try:
            _step(context, run, now)
        except Exception as exc:  # noqa: BLE001 — collected and re-raised below
            failures.append(exc)
    if failures:
        raise ExceptionGroup(f"{len(failures)} strategy run(s) failed a step", failures)


# Commands


def _carry_out(context: RunnerContext, command: Command, now: datetime) -> None:
    if command.kind is CommandKind.START:
        _start(context, command, now)
        return
    if command.kind is CommandKind.SIGNAL:
        _signal(context, command, now)
        return
    with write_transaction() as session:
        run = runs_repo.active_run_of(session, command.strategy_id)
        leg = next((leg for leg in run.legs if leg.leg_id == command.leg_id), None) if run else None
        if run is None:
            outcome = "nothing was running"
        elif command.kind is CommandKind.CLOSE_LEG and (
            leg is None or leg.status is not LegStatus.OPEN
        ):
            outcome, run = f"{command.leg_id} was not open", None
        else:
            outcome = f"closing {command.leg_id}" if leg else f"stopping {run.id}"
        runs_repo.settle_command(session, command.id, CommandStatus.DONE, outcome, now)
    if run is None:
        return
    who = command.triggered_by
    if leg is not None:
        run = _with_leg(run, replace(leg, status=LegStatus.CLOSING, exit_reason="manual"))
        runs_repo.save_run(run)
        runs_repo.add_event(run.id, now, f"{leg.leg_id}: closing, asked by {who}")
    elif command.kind is CommandKind.KILL:
        run = _stopping(run, StrategyStopReason.KILL, f"kill switch by {who}", now)
    else:
        run = _stopping(run, StrategyStopReason.MANUAL, f"stop by {who}", now)
    _close_legs(context, run, now)


def _start(context: RunnerContext, command: Command, now: datetime) -> None:
    stored = strategies_repo.find_strategy(command.strategy_id)
    refusal = _start_refusal(command, stored, now)
    sandbox = None
    resolved = None
    if (
        refusal is None
        and stored is not None
        and isinstance(stored.spec, OptionsStrategySpec)
        and command.broker is not None
    ):
        try:
            sandbox = context.sandbox(command.broker)
            _, _, resolved = resolve_legs(stored.spec, sandbox, now)
            refusal = _closed_market(
                product_for(stored.spec.horizon), resolved[0].instrument, context.calendar, now
            )
            closing = exit_due(
                stored.spec.schedule,
                now,
                {leg.instrument.expiry for leg in resolved if leg.instrument.expiry},
                resolved[0].instrument.exchange,
                context.calendar,
                now,
            )
            if refusal is None and closing is not None:
                refusal = f"its schedule would close it at once ({closing[1]})"
        except Exception as exc:  # noqa: BLE001 — any failure to start is the command's answer
            refusal = str(exc) or type(exc).__name__
    with write_transaction() as session:
        if not any(
            pending.id == command.id
            for pending in runs_repo.pending_commands_of(session, command.strategy_id)
        ):
            return  # cancelled by a stop or a kill while the legs were resolved
        if refusal is None and runs_repo.active_run_of(session, command.strategy_id):
            refusal = "already running"
        if refusal is not None or stored is None or sandbox is None or resolved is None:
            runs_repo.settle_command(
                session, command.id, CommandStatus.REFUSED, refusal or "not started", now
            )
            return
        run = Run(
            id=runs_repo.new_run_id(),
            strategy_id=stored.id,
            broker=command.broker or "",
            product=product_for(stored.spec.horizon),
            status=RunStatus.OPEN,
            trigger=command.triggered_by,
            started_at=now,
            legs=tuple(
                RunLeg(
                    leg_id=leg.leg_id,
                    symbol=leg.instrument.symbol,
                    exchange=leg.instrument.exchange,
                    side=leg.spec.side,
                    quantity=leg.quantity,
                    status=LegStatus.PENDING,
                )
                for leg in resolved
            ),
        )
        runs_repo.insert_run(session, run)
        runs_repo.settle_command(session, command.id, CommandStatus.DONE, f"started {run.id}", now)

    runs_repo.add_event(
        run.id,
        now,
        f"started by {command.triggered_by}: "
        + ", ".join(f"{leg.leg_id} {leg.label} {leg.instrument.symbol}" for leg in resolved),
    )
    specs = {leg.leg_id: leg.spec for leg in resolved}
    for leg in run.legs:
        try:
            result = _place(context, sandbox, run, leg, "entry", leg.side, leg.quantity, now)
        except Exception as exc:
            # The order may have filled before the error: the pending legs are
            # settled from the sandbox by `_close_legs`, then the error is raised
            # for the daemon to log.
            detail = f"{leg.leg_id} could not be entered: {type(exc).__name__}: {exc}"
            _close_legs(context, _stopping(run, StrategyStopReason.ERROR, detail, now), now)
            raise
        if result.status is OrderStatus.FILLED and result.fill_price is not None:
            price = result.fill_price
            run = _with_leg(
                run,
                replace(
                    leg,
                    status=LegStatus.OPEN,
                    entry_price=price,
                    entered_at=now,
                    risk=leg_risk(specs[leg.leg_id], leg.side, price, leg.quantity),
                ),
            )
            runs_repo.save_run(run)
            runs_repo.add_event(run.id, now, f"{leg.leg_id}: {_filled(leg, price)}")
            continue
        reason = result.reason or result.status.value
        run = replace(
            run,
            legs=tuple(
                replace(other, status=LegStatus.FAILED, exit_reason=reason)
                if other.status is LegStatus.PENDING
                else other
                for other in run.legs
            ),
        )
        runs_repo.add_event(run.id, now, f"{leg.leg_id}: entry failed: {reason}")
        run = _stopping(
            run, StrategyStopReason.ERROR, f"{leg.leg_id} could not be entered: {reason}", now
        )
        _close_legs(context, run, now)
        return
    context.events.publish(
        StrategyStarted(
            strategy_id=stored.id,
            run_id=run.id,
            name=stored.name,
            legs=", ".join(_filled(leg, leg.entry_price or 0.0) for leg in run.legs),
            triggered_by=command.triggered_by,
        )
    )


def _start_refusal(command: Command, stored: StoredStrategy | None, now: datetime) -> str | None:
    if now - command.created_at > START_TIMEOUT:
        return (
            "expired: openticker-serve was not running when it was sent; start it, then "
            "start the strategy again"
        )
    if stored is None:
        return "the strategy was deleted"
    if stored.locked:
        return "locked by its kill switch"
    if isinstance(stored.spec, SignalStrategySpec):
        return "a signal strategy enters on its alerts, not on a start"
    if command.broker is None:
        return "no broker named"
    return None


def _closed_market(
    product: Product, contract: Instrument, calendar: MarketCalendar, now: datetime
) -> str | None:
    status = market_status(now, contract.exchange, calendar)
    if not status.is_open:
        opens = status.session.opens_at.strftime("%a %d %b %H:%M")
        return f"{contract.exchange} is closed ({status.closed_reason}); it next opens {opens} IST"
    if product is Product.MIS and not intraday_allowed(now, contract.exchange, calendar):
        return "past the intraday square-off; make the strategy positional, or enter tomorrow"
    return None


# Signals


def _signal(context: RunnerContext, command: Command, now: datetime) -> None:
    """One alert's entry or exit for one leg of a signal strategy. A signal
    strategy has a run per trading day: the first entry opens it, and it
    waits for more alerts while flat, until exit_time or the session's end.
    An entry for a position already held, or an exit for one that isn't, is
    done and does nothing; an entry against a position held the other way
    closes it first."""
    stored = strategies_repo.find_strategy(command.strategy_id)
    refusal = _signal_refusal(command, stored, now)
    if (
        refusal is not None
        or stored is None
        or not isinstance(stored.spec, SignalStrategySpec)
        or command.action is None
        or command.leg_id is None
    ):
        _settle(command, CommandStatus.REFUSED, refusal or "not a signal", now)
        return
    action, spec = command.action, stored.spec
    defined = {leg_id(i): leg for i, leg in enumerate(spec.legs)}.get(command.leg_id)
    if defined is None:
        _settle(command, CommandStatus.REFUSED, f"{stored.name!r} has no {command.leg_id}", now)
        return
    run = runs_repo.find_active_run(stored.id)
    if run is not None and run.status is RunStatus.STOPPING:
        _settle(command, CommandStatus.REFUSED, f"run {run.id} is stopping", now)
        return
    held = _position(run, command.leg_id)
    if held is not None and held.status is not LegStatus.OPEN:
        _settle(
            command,
            CommandStatus.REFUSED,
            f"{held.leg_id} is {held.status}; send the alert again once it settles",
            now,
        )
        return
    move, why = signal_move(action, held.side if held else None)
    if move is Move.NONE:
        _settle(command, CommandStatus.DONE, why, now)
        return
    if run is not None and held is not None:  # EXIT, or the first half of a FLIP
        if move is Move.EXIT:
            _settle(command, CommandStatus.DONE, f"{why}: {held.leg_id}", now)
        run = _with_leg(run, replace(held, status=LegStatus.CLOSING, exit_reason="signal"))
        runs_repo.save_run(run)
        runs_repo.add_event(run.id, now, f"{held.leg_id}: closing, {action} alert")
        _close_legs(context, run, now)
        if move is Move.EXIT:
            return
        run = runs_repo.find_run(run.id)
        if run is None or _leg(run, held.leg_id).status is not LegStatus.CLOSED:
            _settle(
                command,
                CommandStatus.REFUSED,
                f"{held.leg_id}'s exit has not filled, so no {action} was entered; its exit "
                "is being retried",
                now,
            )
            return
    _enter_signal(context, command, stored, defined, run, why, now)


def _enter_signal(
    context: RunnerContext,
    command: Command,
    stored: StoredStrategy,
    defined: SignalLeg,
    run: Run | None,
    why: str,
    now: datetime,
) -> None:
    assert isinstance(stored.spec, SignalStrategySpec) and command.action and command.leg_id
    product = product_for(stored.spec.horizon)
    instrument = get_instrument(defined.symbol, defined.exchange.value)
    refusal = (
        f"{defined.symbol} is no longer in the instrument master; run sync_instruments"
        if instrument is None
        else _closed_market(product, instrument, context.calendar, now)
    )
    sandbox = None
    if refusal is None:
        try:
            sandbox = context.sandbox(command.broker or "")
        except Exception as exc:  # noqa: BLE001 — any failure to reach the broker is the answer
            refusal = str(exc) or type(exc).__name__
    if refusal is not None or sandbox is None:
        _settle(command, CommandStatus.REFUSED, refusal or "no sandbox", now)
        return
    opened = run is None
    run = run or Run(
        id=runs_repo.new_run_id(),
        strategy_id=stored.id,
        broker=command.broker or "",
        product=product,
        status=RunStatus.OPEN,
        trigger=WEBHOOK_TRIGGER,
        started_at=now,
        legs=(),
    )
    count = sum(1 for leg in run.legs if leg.defined_as == command.leg_id)
    leg = RunLeg(
        leg_id=command.leg_id if count == 0 else f"{command.leg_id}.{count + 1}",
        symbol=defined.symbol,
        exchange=defined.exchange,
        side=command.action.side,
        quantity=defined.quantity,
        status=LegStatus.PENDING,
        spec_leg=command.leg_id,
    )
    run = replace(run, legs=(*run.legs, leg))
    # The pending leg and the command's answer are written together: a daemon
    # that dies before the order is answered reconciles the leg, and never
    # carries out the alert twice.
    with write_transaction() as session:
        if opened:
            runs_repo.insert_run(session, run)
        else:
            runs_repo.update_run(session, run)
        runs_repo.settle_command(
            session, command.id, CommandStatus.DONE, f"{why}: {leg.leg_id}", now
        )
    if opened:
        runs_repo.add_event(run.id, now, f"opened by an alert for {command.leg_id}")
    result = _place(context, sandbox, run, leg, "entry", leg.side, leg.quantity, now)
    if result.status is OrderStatus.FILLED and result.fill_price is not None:
        price = result.fill_price
        entered = replace(
            leg,
            status=LegStatus.OPEN,
            entry_price=price,
            entered_at=now,
            risk=leg_risk(defined, leg.side, price, leg.quantity),
        )
        runs_repo.add_event(run.id, now, f"{leg.leg_id}: {_filled(leg, price)}, {command.action}")
    else:
        reason = result.reason or result.status.value
        entered = replace(leg, status=LegStatus.FAILED, exit_reason=reason)
        runs_repo.add_event(run.id, now, f"{leg.leg_id}: entry failed: {reason}")
    run = _with_leg(run, entered)
    runs_repo.save_run(run)
    if opened and entered.status is LegStatus.OPEN:
        context.events.publish(
            StrategyStarted(
                strategy_id=stored.id,
                run_id=run.id,
                name=stored.name,
                legs=_filled(entered, entered.entry_price or 0.0),
                triggered_by=WEBHOOK_TRIGGER,
            )
        )


def _signal_refusal(command: Command, stored: StoredStrategy | None, now: datetime) -> str | None:
    if now - command.created_at > START_TIMEOUT:
        return "expired: openticker-serve was not running when it arrived"
    if stored is None:
        return "the strategy was deleted"
    if stored.locked:
        return "locked by its kill switch"
    if not isinstance(stored.spec, SignalStrategySpec):
        return "not a signal strategy"
    return None


def _position(run: Run | None, defined: str) -> RunLeg | None:
    """The run's position on a defined leg: not yet closed, the latest."""
    if run is None:
        return None
    return next(
        (
            leg
            for leg in reversed(run.legs)
            if leg.defined_as == defined
            and leg.status in (LegStatus.PENDING, LegStatus.OPEN, LegStatus.CLOSING)
        ),
        None,
    )


def _settle(command: Command, status: CommandStatus, outcome: str, now: datetime) -> None:
    with write_transaction() as session:
        runs_repo.settle_command(session, command.id, status, outcome, now)


def _waits_for_signals(run: Run) -> bool:
    """A signal run stays open while flat, for the day's next alert."""
    return run.trigger == WEBHOOK_TRIGGER and run.status is RunStatus.OPEN


def _day_over(
    context: RunnerContext, run: Run, stored: StoredStrategy | None, now: datetime
) -> tuple[StrategyStopReason, str] | None:
    """Why a flat signal run ends now: its exit_time, or its session's close."""
    if stored is None or not isinstance(stored.spec, SignalStrategySpec):
        return StrategyStopReason.MANUAL, "the strategy was deleted"
    exchange = run.legs[0].exchange if run.legs else stored.spec.legs[0].exchange
    closing = exit_due(stored.spec.schedule, run.started_at, set(), exchange, context.calendar, now)
    if closing is not None:
        return closing
    started = run.started_at.astimezone(EXCHANGE_TIMEZONE).date()
    hours = session_hours(started, exchange, context.calendar)
    if hours is None or now >= hours.closes_at:
        return StrategyStopReason.SCHEDULE, "the session ended"
    return None


# Watching a run


def _step(context: RunnerContext, run: Run, now: datetime) -> None:
    run = _reconcile(context, run, now)
    if run.status is RunStatus.STOPPING:
        _close_legs(context, run, now)
        return
    held = [leg for leg in run.legs if leg.is_open]
    if not held:
        if _waits_for_signals(run):
            over = _day_over(context, run, strategies_repo.find_strategy(run.strategy_id), now)
            if over is None:
                return
            run = _stopping(run, *over, now)
        _close_legs(context, run, now)  # ends it
        return
    if run.product is Product.MIS and not intraday_allowed(now, held[0].exchange, context.calendar):
        run = _stopping(run, StrategyStopReason.SCHEDULE, "intraday square-off", now)
        _close_legs(context, run, now)
        return

    stored = strategies_repo.find_strategy(run.strategy_id)
    instruments = {leg.leg_id: get_instrument(leg.symbol, leg.exchange.value) for leg in held}
    if stored is not None:
        closing = exit_due(
            stored.spec.schedule,
            run.started_at,
            {i.expiry for i in instruments.values() if i is not None and i.expiry is not None},
            held[0].exchange,
            context.calendar,
            now,
        )
        if closing is not None:
            _close_legs(context, _stopping(run, *closing, now), now)
            return
    ticks = {
        leg_id: context.latest(instrument) if instrument else None
        for leg_id, instrument in instruments.items()
    }
    opens = _session_opened(held[0].exchange, context.calendar, now)
    stale = [
        leg.symbol
        for leg in held
        if opens is not None
        and is_stale(
            watched_since(leg.entered_at, opens, context.watching_from),
            tick.received_at if (tick := ticks[leg.leg_id]) else None,
            now,
            context.timeouts,
        )
    ]
    if stale:
        seconds = int(context.timeouts.stale_after.total_seconds())
        detail = f"no price, streamed or quoted, for {seconds}s: {', '.join(stale)}"
        _close_legs(context, _stopping(run, StrategyStopReason.TICK_STALE, detail, now), now)
        return

    limits = stored.spec.limits if stored else StrategyLimits()
    today = now.astimezone(EXCHANGE_TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    prices: dict[str, float] = {}
    for leg in held:
        tick = ticks[leg.leg_id]
        # Only a price from after the entry: an older one says nothing about this position.
        if tick is not None and leg.entered_at is not None and tick.received_at > leg.entered_at:
            prices[leg.leg_id] = tick.last_price
    decision = evaluate_strategy(
        StrategyRisk(
            limits=limits,
            peak_mtm=run.peak_mtm,
            lock_floor=run.lock_floor,
            stops_at_entry=run.stops_at_entry,
            earlier_runs_realized_pnl=runs_repo.realized_since(run.strategy_id, today, run.id),
        ),
        [LegState(leg.leg_id, _watched(leg), leg.realized_pnl) for leg in run.legs],
        prices,
    )

    ratchets = {state.leg_id: state.risk for state in decision.legs}
    updated = replace(
        run,
        legs=tuple(
            replace(leg, risk=ratchets.get(leg.leg_id)) if leg.status is LegStatus.OPEN else leg
            for leg in run.legs
        ),
        peak_mtm=decision.peak_mtm,
        trough_mtm=run.trough_mtm if decision.mtm is None else min(run.trough_mtm, decision.mtm),
        lock_floor=decision.lock_floor,
        stops_at_entry=decision.stops_at_entry,
    )
    notes: list[str] = []
    if decision.stops_moved_to_entry:
        notes.append(f"stops moved to entry on {', '.join(decision.stops_moved_to_entry)}")
    if decision.lock_floor is not None and decision.lock_floor != run.lock_floor:
        notes.append(f"profit locked at {decision.lock_floor:,.2f}")

    if decision.exit_all is not None:
        if updated != run:
            runs_repo.save_run(updated)
        for note in notes:
            runs_repo.add_event(run.id, now, note)
        updated = _stopping(updated, decision.exit_all, decision.detail or "", now)
    else:
        exiting = {
            exit.leg_id: exit
            for exit in decision.leg_exits
            if _leg(updated, exit.leg_id).status is LegStatus.OPEN
        }
        for leg_id, exit in exiting.items():
            leg = _leg(updated, leg_id)
            updated = _with_leg(
                updated, replace(leg, status=LegStatus.CLOSING, exit_reason=exit.reason.value)
            )
            notes.append(f"{leg_id}: {exit.detail}")
        if updated != run:
            runs_repo.save_run(updated)
        for note in notes:
            runs_repo.add_event(run.id, now, note)
    if any(leg.status is LegStatus.CLOSING for leg in updated.legs):
        _close_legs(context, updated, now)


def _watched(leg: RunLeg) -> PositionRisk | None:
    """A closing leg still counts towards the run's P&L, but its own rules
    have already fired: without them it can't exit again, or move the other
    legs' stops."""
    if not leg.is_open or leg.risk is None:
        return None
    if leg.status is LegStatus.OPEN:
        return leg.risk
    return replace(leg.risk, initial_sl=None, current_sl=None, target=None, trailing=None)


def _stopping(run: Run, reason: StrategyStopReason, detail: str, now: datetime) -> Run:
    """Marks the run stopping and every held leg closing, and saves it."""
    run = replace(
        run,
        status=RunStatus.STOPPING,
        stop_reason=reason,
        stop_detail=detail,
        legs=tuple(
            replace(leg, status=LegStatus.CLOSING, exit_reason=leg.exit_reason or reason.value)
            if leg.status is LegStatus.OPEN
            else leg
            for leg in run.legs
        ),
    )
    runs_repo.save_run(run)
    runs_repo.add_event(run.id, now, f"stopping ({reason}): {detail}")
    return run


def _close_legs(context: RunnerContext, run: Run, now: datetime) -> None:
    """Sends an exit for every closing leg due one, then ends the run once
    nothing is held."""
    run = _reconcile(context, run, now)
    closing = [
        leg
        for leg in run.legs
        if leg.status is LegStatus.CLOSING and (leg.retry_at is None or leg.retry_at <= now)
    ]
    if closing:
        sandbox = context.sandbox(run.broker)
        held = {
            (position.instrument.exchange, position.instrument.symbol): position.quantity
            for position in sandbox.open_positions()
            if position.product is run.product
        }
        for leg in closing:
            run = _with_leg(run, _exit(context, sandbox, run, leg, held, now))
            runs_repo.save_run(run)
    if not _waits_for_signals(run) and not any(
        leg.is_open or leg.status is LegStatus.PENDING for leg in run.legs
    ):
        _end(context, run, now)


class _Unreconcilable(Exception):
    """The records and the sandbox disagree in a way the runner won't guess at."""


def _reconcile(context: RunnerContext, run: Run, now: datetime) -> Run:
    """Takes in orders whose outcome the run never recorded, because placing
    one raised or the daemon stopped in between (ADR 14 and ADR 23 in
    docs/adr). The sandbox, which tags every order with its run, says what
    happened:

    - A pending leg whose entry filled is held and watched, or closed if the
      run is stopping; one whose entry never filled has failed, and a run left
      partly entered stops, as a failed entry does in `_start`.
    - A closing leg whose exit filled is closed at that fill.

    When they can't be matched, the run stops with reason `recovery_failed`
    and closes what the sandbox holds for it, at no made-up price."""
    if not any(leg.status in (LegStatus.PENDING, LegStatus.CLOSING) for leg in run.legs):
        return run
    orders = runs_repo.list_orders(run.id)
    latest = {(order.leg_id, order.intent): order for order in orders}  # the last of each
    pending = [leg for leg in run.legs if leg.status is LegStatus.PENDING]
    exits = [
        (leg, order)
        for leg in run.legs
        if leg.status is LegStatus.CLOSING
        and (order := latest.get((leg.leg_id, "exit"))) is not None
        and (order.status == "pending" or order.status == OrderStatus.FILLED.value)
    ]
    if not pending and not exits:
        return run
    sandbox = context.sandbox(run.broker)
    claimed = {order.sandbox_order_id for order in orders if order.sandbox_order_id}
    unclaimed = [o for o in sandbox.orders_of_run(run.id) if o.order_id not in claimed]
    try:
        for leg in pending:
            entry = latest.get((leg.leg_id, "entry"))
            placed = _answer(sandbox, entry, unclaimed, now) if entry else None
            run = _with_leg(run, _entered(run, leg, placed, now))
        for leg, order in exits:
            placed = _answer(sandbox, order, unclaimed, now)
            if placed and placed.status is OrderStatus.FILLED and placed.fill_price is not None:
                closed = replace(
                    leg,
                    status=LegStatus.CLOSED,
                    quantity=placed.quantity,
                    exit_price=placed.fill_price,
                    retry_at=None,
                )
                runs_repo.add_event(
                    run.id,
                    now,
                    f"{leg.leg_id}: found closed ({leg.exit_reason}) at {placed.fill_price}, "
                    f"P&L {closed.realized_pnl:+,.2f}",
                )
                _publish_closed(context, run, closed, f"{leg.exit_reason}: exit filled")
                run = _with_leg(run, closed)
    except _Unreconcilable as exc:
        runs_repo.add_event(run.id, now, f"recovery failed: {exc}")
        # An entry nobody can account for is closed as if held: the exit never
        # trades more than the sandbox holds, so it can't open a position.
        run = replace(
            run,
            legs=tuple(
                replace(leg, status=LegStatus.CLOSING, exit_reason="recovery_failed")
                if leg.status is LegStatus.PENDING
                else leg
                for leg in run.legs
            ),
        )
        runs_repo.save_run(run)
        if run.status is RunStatus.OPEN:
            run = _stopping(run, StrategyStopReason.RECOVERY_FAILED, str(exc), now)
        return run
    runs_repo.save_run(run)
    failed = [leg.leg_id for leg in pending if _leg(run, leg.leg_id).status is LegStatus.FAILED]
    # A signal run carries on past a failed entry, as it does when placing one.
    if failed and run.status is RunStatus.OPEN and not _waits_for_signals(run):
        run = _stopping(
            run, StrategyStopReason.ERROR, f"{', '.join(failed)} could not be entered", now
        )
    return run


def _answer(
    sandbox: OrderSandbox, order: RunOrder, unclaimed: list[Order], now: datetime
) -> Order | None:
    """The sandbox's order for a recorded one, or None if it never got there.
    An order recorded without the sandbox's id is matched to the one order of
    the run it hasn't been matched to yet: orders go one at a time, so there is
    at most one."""
    if order.sandbox_order_id is not None:
        placed = sandbox.get_order(order.sandbox_order_id)
        if placed is None:
            runs_repo.settle_order(
                order.id, "unreconciled", order.sandbox_order_id, None, None, now
            )
            raise _Unreconcilable(
                f"{order.leg_id}'s {order.intent} {order.sandbox_order_id} is not in the sandbox"
            )
        return placed
    placed = next((o for o in unclaimed if o.instrument.symbol == order.symbol), None)
    if placed is None:
        runs_repo.settle_order(order.id, "not_sent", None, None, None, now)
        return None
    runs_repo.settle_order(
        order.id, placed.status.value, placed.order_id, placed.fill_price, placed.reason, now
    )
    return placed


def _entered(run: Run, leg: RunLeg, placed: Order | None, now: datetime) -> RunLeg:
    if placed is None or placed.status is not OrderStatus.FILLED or placed.fill_price is None:
        reason = (placed.reason or placed.status.value) if placed else "never reached the sandbox"
        runs_repo.add_event(run.id, now, f"{leg.leg_id}: entry failed: {reason}")
        return replace(leg, status=LegStatus.FAILED, exit_reason=reason)
    price = placed.fill_price
    stored = strategies_repo.find_strategy(run.strategy_id)
    defined: tuple[LegSpec | SignalLeg, ...] = stored.spec.legs if stored else ()
    specs = {leg_id(i): spec for i, spec in enumerate(defined)}
    spec = specs.get(leg.defined_as)
    stopping = run.status is RunStatus.STOPPING
    runs_repo.add_event(run.id, now, f"{leg.leg_id}: found filled, {_filled(leg, price)}")
    return replace(
        leg,
        status=LegStatus.CLOSING if stopping else LegStatus.OPEN,
        entry_price=price,
        entered_at=placed.placed_at,
        exit_reason=run.stop_reason.value if stopping and run.stop_reason else None,
        risk=leg_risk(spec, leg.side, price, leg.quantity) if spec else None,
    )


def _exit(
    context: RunnerContext,
    sandbox: OrderSandbox,
    run: Run,
    leg: RunLeg,
    held: dict[tuple[Exchange, str], int],
    now: datetime,
) -> RunLeg:
    # Never exit more than the sandbox holds in the leg's direction: the
    # session's square-off, an expiry settlement or a hand-placed order may
    # have closed it already, and selling what isn't held would open a position.
    net = held.get((leg.exchange, leg.symbol), 0)
    available = max(net, 0) if leg.side is Side.BUY else max(-net, 0)
    quantity = min(leg.quantity, available)
    if quantity == 0:
        instrument = get_instrument(leg.symbol, leg.exchange.value)
        tick = context.latest(instrument) if instrument else None
        closed = replace(
            leg,
            status=LegStatus.CLOSED,
            exit_price=tick.last_price if tick else None,
            retry_at=None,
        )
        runs_repo.add_event(
            run.id, now, f"{leg.leg_id}: already closed outside the strategy; nothing to exit"
        )
        _publish_closed(context, run, closed, "closed outside the strategy")
        return closed
    exit_side = Side.SELL if leg.side is Side.BUY else Side.BUY
    result = _place(context, sandbox, run, leg, "exit", exit_side, quantity, now)
    if result.status is OrderStatus.FILLED and result.fill_price is not None:
        # A partial exit counts only what this run closed; the rest was closed
        # by whatever emptied the position.
        closed = replace(
            leg,
            status=LegStatus.CLOSED,
            quantity=quantity,
            exit_price=result.fill_price,
            retry_at=None,
        )
        partial = "" if quantity == leg.quantity else f" (only {quantity} was still held)"
        runs_repo.add_event(
            run.id,
            now,
            f"{leg.leg_id}: closed ({leg.exit_reason}) at {result.fill_price}{partial}, "
            f"P&L {closed.realized_pnl:+,.2f}",
        )
        _publish_closed(context, run, closed, f"{leg.exit_reason}: exit filled{partial}")
        return closed
    wait = min(EXIT_RETRY * 2**leg.failed_exits, EXIT_RETRY_MAX)
    runs_repo.add_event(
        run.id,
        now,
        f"{leg.leg_id}: exit failed: {result.reason or result.status}; trying again in "
        f"{int(wait.total_seconds())}s",
    )
    return replace(leg, retry_at=now + wait, failed_exits=leg.failed_exits + 1)


def _end(context: RunnerContext, run: Run, now: datetime) -> None:
    reason = run.stop_reason or StrategyStopReason.LEGS_CLOSED
    detail = run.stop_detail or "every leg exited on its own rules"
    run = replace(run, status=RunStatus.ENDED, stop_reason=reason, stop_detail=detail, ended_at=now)
    runs_repo.save_run(run)
    runs_repo.add_event(run.id, now, f"ended ({reason}), P&L {run.realized_pnl:+,.2f}")
    stored = strategies_repo.find_strategy(run.strategy_id)
    context.events.publish(
        StrategyStopped(
            strategy_id=run.strategy_id,
            run_id=run.id,
            name=stored.name if stored else run.strategy_id,
            reason=reason.value,
            detail=detail,
            realized_pnl=run.realized_pnl,
        )
    )


def _place(
    context: RunnerContext,
    sandbox: OrderSandbox,
    run: Run,
    leg: RunLeg,
    intent: str,
    side: Side,
    quantity: int,
    now: datetime,
) -> OrderResult:
    order_id = runs_repo.add_order(run.id, leg, intent, side, quantity, now)
    instrument = get_instrument(leg.symbol, leg.exchange.value)
    if instrument is None:
        result = OrderResult(
            status=OrderStatus.REJECTED,
            broker_order_id=None,
            reason=f"{leg.symbol} is no longer in the instrument master; run sync_instruments",
        )
    else:
        result = place_order(
            OrderRequest(
                instrument=instrument,
                side=side,
                quantity=quantity,
                product=run.product,
                order_type=OrderType.MARKET,
                price=None,
                triggered_by=f"strategy:{run.strategy_id}",
                strategy_id=run.strategy_id,
                run_id=run.id,
            ),
            sandbox,
            context.events,
            context.capital_cap if intent == "entry" else None,
            context.calendar,
            now,
        )
    runs_repo.settle_order(
        order_id, result.status.value, result.broker_order_id, result.fill_price, result.reason, now
    )
    return result


def _publish_closed(context: RunnerContext, run: Run, leg: RunLeg, detail: str) -> None:
    context.events.publish(
        StrategyLegClosed(
            strategy_id=run.strategy_id,
            run_id=run.id,
            leg_id=leg.leg_id,
            symbol=leg.symbol,
            reason=leg.exit_reason or "",
            detail=detail,
            realized_pnl=round(leg.realized_pnl, 2),
        )
    )


def _filled(leg: RunLeg, price: float) -> str:
    return f"{leg.side} {leg.quantity} {leg.symbol} @ {price}"


def _leg(run: Run, leg_id: str) -> RunLeg:
    return next(leg for leg in run.legs if leg.leg_id == leg_id)


def _with_leg(run: Run, leg: RunLeg) -> Run:
    return replace(
        run, legs=tuple(leg if other.leg_id == leg.leg_id else other for other in run.legs)
    )
