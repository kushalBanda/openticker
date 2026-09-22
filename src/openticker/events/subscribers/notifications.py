"""Turns the events a user should hear about into messages and sends them to
every configured channel. Subscribed in the background: a slow or failing
channel never delays the use case that published the event."""

from collections.abc import Callable, Sequence

from openticker.events.types import OrderFailed, OrderFilled, RiskBreached
from openticker.ports.notification_port import NotificationPort

# OrderPlaced is audited, not notified: a market order fills at once, and one
# message per order is enough.
NOTIFIED_EVENTS: tuple[type, ...] = (OrderFilled, OrderFailed, RiskBreached)


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
