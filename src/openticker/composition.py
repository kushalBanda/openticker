"""Composition root: builds the event bus, its subscribers and the sandbox
settings from configuration. The one module allowed to wire events, storage and outbound
adapters together; entry points (`openticker-mcp`) call it, nothing else does."""

import math
from collections.abc import Mapping

from openticker.adapters.notifications.email import EmailAdapter, SmtpSettings
from openticker.adapters.notifications.slack import SlackAdapter
from openticker.adapters.sandbox.broker import SandboxSettings
from openticker.events.bus import EventBus
from openticker.events.subscribers.audit_log import record_event
from openticker.events.subscribers.notifications import NOTIFIED_EVENTS, notifier
from openticker.ports.notification_port import NotificationPort

# NOTIFY_EMAIL_FROM has no default: for Resend and Amazon SES the SMTP username
# is not an email address ("resend", an access key id), so it can't be the sender.
_SMTP_REQUIRED = (
    "SMTP_HOST",
    "SMTP_USERNAME",
    "SMTP_PASSWORD",
    "NOTIFY_EMAIL_FROM",
    "NOTIFY_EMAIL_TO",
)


class NotificationConfigError(Exception):
    """Notification settings are present but incomplete."""


class SandboxConfigError(Exception):
    """A sandbox setting is not a positive number."""


def build_event_bus(env: Mapping[str, str]) -> EventBus:
    bus = EventBus()
    bus.subscribe(object, record_event, background=False)
    channels = notification_channels(env)
    if channels:
        notify = notifier(channels)
        for event_type in NOTIFIED_EVENTS:
            bus.subscribe(event_type, notify)
    return bus


def notification_channels(env: Mapping[str, str]) -> list[NotificationPort]:
    """Every channel whose settings are present. None configured is valid:
    events are still audited, just not sent anywhere."""
    channels: list[NotificationPort] = []
    if webhook_url := env.get("SLACK_WEBHOOK_URL"):
        channels.append(SlackAdapter(webhook_url))
    smtp_present = [name for name in _SMTP_REQUIRED if env.get(name)]
    if smtp_present:
        missing = [name for name in _SMTP_REQUIRED if not env.get(name)]
        if missing:
            raise NotificationConfigError(
                f"email notifications need {', '.join(missing)} as well (see .env.example)"
            )
        port = env.get("SMTP_PORT") or "587"
        if not port.isdigit():
            raise NotificationConfigError(f"SMTP_PORT must be a number, got {port!r}")
        channels.append(
            EmailAdapter(
                SmtpSettings(
                    host=env["SMTP_HOST"],
                    port=int(port),
                    username=env["SMTP_USERNAME"],
                    password=env["SMTP_PASSWORD"],
                    sender=env["NOTIFY_EMAIL_FROM"],
                    recipient=env["NOTIFY_EMAIL_TO"],
                )
            )
        )
    return channels


def sandbox_settings(env: Mapping[str, str]) -> SandboxSettings:
    """`SANDBOX_STARTING_CAPITAL` applies when sandbox funds are first created."""
    capital = _positive_number(env, "SANDBOX_STARTING_CAPITAL")
    return SandboxSettings() if capital is None else SandboxSettings(starting_capital=capital)


def capital_cap(env: Mapping[str, str]) -> float | None:
    """`OPENTICKER_CAPITAL_CAP`: the most one position may be worth. Unset means no cap."""
    return _positive_number(env, "OPENTICKER_CAPITAL_CAP")


def _positive_number(env: Mapping[str, str], name: str) -> float | None:
    raw = env.get(name)
    if not raw:
        return None
    try:
        value = float(raw.replace(",", "").replace("_", ""))
    except ValueError:
        value = 0.0
    if not (math.isfinite(value) and value > 0):
        raise SandboxConfigError(f"{name} must be a positive number, got {raw!r}")
    return value
