"""The strategy runner, called only by the daemon (ADR 21 in docs/adr).

`process_commands` carries out what the MCP server and the REST API asked
for: start, stop, kill, close a leg. `step_runs` judges every open run at the
latest live prices, each leg on its own rules and the whole run on the
strategy's (ADR 19), and closes what those rules say to close.

Every order is recorded in `strategy_orders` before it is sent. A run's legs,
ratchets and stop reason are saved as they change, so a restarted daemon
carries on watching them.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from openticker.core.calendar.calendar import intraday_allowed, market_status
from openticker.core.calendar.models import MarketCalendar
from openticker.core.orders.models import OrderRequest, OrderResult, OrderStatus, OrderType
from openticker.core.risk.aggregate import evaluate_strategy
from openticker.core.risk.models import (
    LegState,
    PositionRisk,
    StrategyLimits,
    StrategyRisk,
    StrategyStopReason,
)
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
from openticker.events.bus import EventPublisher
from openticker.events.types import StrategyLegClosed, StrategyStarted, StrategyStopped
from openticker.ports.models import EXCHANGE_TIMEZONE, Exchange, Instrument, Product, Side, Tick
from openticker.ports.sandbox_port import OrderSandbox
from openticker.storage.sqlite import runs_repo, strategies_repo
from openticker.storage.sqlite.instruments_repo import get_instrument
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
    if refusal is None and stored is not None and command.broker is not None:
        try:
            sandbox = context.sandbox(command.broker)
            _, _, resolved = resolve_legs(stored.spec, sandbox, now)
            refusal = _closed_market(stored, resolved[0].instrument, context.calendar, now)
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
        result = _place(context, sandbox, run, leg, "entry", leg.side, leg.quantity, now)
        if result.status is OrderStatus.FILLED and result.fill_price is not None:
            price = result.fill_price
            run = _with_leg(
                run,
                replace(
                    leg,
                    status=LegStatus.OPEN,
                    entry_price=price,
                    entered_at=now,
                    risk=leg_risk(specs[leg.leg_id], price, leg.quantity),
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
    if command.broker is None:
        return "no broker named"
    return None


def _closed_market(
    stored: StoredStrategy, contract: Instrument, calendar: MarketCalendar, now: datetime
) -> str | None:
    status = market_status(now, contract.exchange, calendar)
    if not status.is_open:
        opens = status.session.opens_at.strftime("%a %d %b %H:%M")
        return f"{contract.exchange} is closed ({status.closed_reason}); it next opens {opens} IST"
    if product_for(stored.spec.horizon) is Product.MIS and not intraday_allowed(
        now, contract.exchange, calendar
    ):
        return "past the intraday square-off; start a positional strategy, or start tomorrow"
    return None


# Watching a run


def _step(context: RunnerContext, run: Run, now: datetime) -> None:
    if run.status is RunStatus.STOPPING:
        _close_legs(context, run, now)
        return
    held = [leg for leg in run.legs if leg.is_open]
    if not held:
        _close_legs(context, run, now)  # ends it
        return
    if run.product is Product.MIS and not intraday_allowed(now, held[0].exchange, context.calendar):
        run = _stopping(run, StrategyStopReason.SCHEDULE, "intraday square-off", now)
        _close_legs(context, run, now)
        return

    stored = strategies_repo.find_strategy(run.strategy_id)
    limits = stored.spec.limits if stored else StrategyLimits()
    today = now.astimezone(EXCHANGE_TIMEZONE).replace(hour=0, minute=0, second=0, microsecond=0)
    prices: dict[str, float] = {}
    for leg in held:
        instrument = get_instrument(leg.symbol, leg.exchange.value)
        tick = context.latest(instrument) if instrument else None
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
    if not any(leg.is_open or leg.status is LegStatus.PENDING for leg in run.legs):
        _end(context, run, now)


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
