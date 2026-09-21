"""Turns the events a user should hear about into messages and sends them to
every configured channel. Subscribed in the background: a slow or failing
channel never delays the use case that published the event."""

from collections.abc import Callable, Sequence

from openticker.events.types import OrderFailed, OrderPlaced, RiskBreached
from openticker.ports.notification_port import NotificationPort

NOTIFIED_EVENTS: tuple[type, ...] = (OrderPlaced, OrderFailed, RiskBreached)


def describe(event: object) -> tuple[str, str] | None:
    """(subject, message) for an event worth a notification, else None."""
    match event:
        case OrderPlaced():
            return (
                f"Order placed: {event.side} {event.quantity} {event.symbol}",
                f"Order {event.order_id} placed via {event.triggered_by}.",
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
