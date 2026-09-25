"""Turns the events a user should hear about into messages and sends them to
every configured channel. Subscribed in the background: a slow or failing
channel never delays the use case that published the event."""

from collections.abc import Callable, Sequence

from openticker.events.types import (
    AgentJobEnded,
    BrokerSessionExpired,
    ChargeRatesDiffer,
    OrderFailed,
    OrderFilled,
    PositionSettled,
    RiskBreached,
    ScriptExited,
    ScriptStarted,
    StrategyLegClosed,
    StrategyStarted,
    StrategyStopped,
)
from openticker.ports.notification_port import NotificationPort

# OrderPlaced is audited, not notified: a market order fills at once, and one
# message per order is enough.
NOTIFIED_EVENTS: tuple[type, ...] = (
    OrderFilled,
    OrderFailed,
    RiskBreached,
    BrokerSessionExpired,
    PositionSettled,
    StrategyStarted,
    StrategyLegClosed,
    StrategyStopped,
    ScriptStarted,
    ScriptExited,
    ChargeRatesDiffer,
    AgentJobEnded,
)


def describe(event: object) -> tuple[str, str] | None:
    """(subject, message) for an event worth a notification, else None."""
    match event:
        case OrderFilled():
            return (
                f"Order filled: {event.side} {event.quantity} {event.symbol} @ {event.price:,.2f}",
                f"Sandbox order {event.order_id} filled via {event.triggered_by}.",
            )
        case OrderFailed():
            return (
                f"Order failed: {event.symbol}",
                f"{event.reason} (via {event.triggered_by}).",
            )
        case RiskBreached():
            return f"Risk breached: {event.symbol} ({event.reason})", event.detail
        case PositionSettled():
            subject = (
                f"Expired: {event.symbol} settled at {event.price:,.2f}, "
                f"P&L {event.realized_pnl:+,.2f}"
            )
            return subject, f"{event.quantity} {event.product} closed at expiry. {event.detail}"
        case StrategyStarted():
            return f"Strategy started: {event.name}", f"Entered {event.legs}."
        case StrategyLegClosed():
            subject = (
                f"Strategy leg closed: {event.symbol} ({event.reason}), "
                f"P&L {event.realized_pnl:+,.2f}"
            )
            return subject, event.detail
        case StrategyStopped():
            subject = (
                f"Strategy stopped: {event.name} ({event.reason}), P&L {event.realized_pnl:+,.2f}"
            )
            return subject, event.detail
        case ScriptStarted():
            return f"Script started: {event.name}", f"Run {event.run_id}, via {event.triggered_by}."
        case ScriptExited():
            return (
                f"Script ended: {event.name} ({event.reason})",
                f"Run {event.run_id} {event.detail}.",
            )
        case BrokerSessionExpired():
            return f"Log in to {event.broker}: live prices stopped", event.detail
        case AgentJobEnded():
            cost = f" Cost ${event.cost_usd:.2f}." if event.cost_usd is not None else ""
            if event.reason == "finished" and event.summary:
                headline = event.summary.strip().splitlines()[0][:120]
                return (
                    f"{event.kind.capitalize()} of {event.strategy_name}: {headline}",
                    f"{event.summary}\n\nJob {event.job_id}.{cost}",
                )
            return (
                f"{event.kind.capitalize()} of {event.strategy_name} {event.reason}",
                f"{event.detail}. Job {event.job_id}; get_agent_job_log shows its output.{cost}",
            )
        case ChargeRatesDiffer():
            subject = (
                f"Charge rates differ from {event.broker}'s: "
                f"{event.differing} of {event.checked} samples"
            )
            return subject, (
                f"{event.detail}. The rates are dated {event.rates_as_of}; update "
                "$OPENTICKER_HOME/charges.json, which replaces the shipped file."
            )
    return None


def notifier(channels: Sequence[NotificationPort]) -> Callable[[object], None]:
    def notify(event: object) -> None:
        described = describe(event)
        if described is None:
            return
        subject, message = described
        failures: list[Exception] = []
        for channel in channels:
            try:
                channel.send(subject, message)
            except Exception as exc:  # noqa: BLE001 — one failing channel must not silence the rest; re-raised below
                failures.append(exc)
        if failures:
            raise ExceptionGroup(f"{len(failures)} notification channel(s) failed", failures)

    return notify
