"""Composition root: builds the event bus, its subscribers and the sandbox
from configuration. The one module allowed to wire events, storage and outbound
adapters together; entry points (`openticker-mcp`, `openticker-serve`) call it,
nothing else does."""

import math
from collections.abc import Mapping
from datetime import timedelta

from openticker.adapters.brokers.registry import get_adapter
from openticker.adapters.notifications.email import EmailAdapter, SmtpSettings
from openticker.adapters.notifications.slack import SlackAdapter
from openticker.adapters.sandbox.broker import SandboxBroker, SandboxSettings
from openticker.core.strategies.prices import PriceTimeouts
from openticker.events.bus import EventBus
from openticker.events.subscribers.audit_log import record_event
from openticker.events.subscribers.notifications import NOTIFIED_EVENTS, notifier
from openticker.ports.models import Exchange
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


class WatchConfigError(Exception):
    """`OPENTICKER_WATCH` is malformed."""


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


def order_broker(broker: str, env: Mapping[str, str]) -> SandboxBroker:
    """The sandbox, pricing through the named broker (ADR 11 in docs/adr)."""
    return SandboxBroker(broker, get_adapter(broker), sandbox_settings(env))


def capital_cap(env: Mapping[str, str]) -> float | None:
    """`OPENTICKER_CAPITAL_CAP`: the most one position may be worth. Unset means no cap."""
    return _positive_number(env, "OPENTICKER_CAPITAL_CAP")


def price_timeouts(env: Mapping[str, str]) -> PriceTimeouts:
    """`STRATEGY_TICK_FALLBACK_SECONDS` (default 10): no streamed price for this
    long and a strategy leg is priced by quotes. `STRATEGY_TICK_STALE_SECONDS`
    (default 60): no price from either and its run stops (ADR 23 in docs/adr)."""
    defaults = PriceTimeouts()
    poll = _positive_number(env, "STRATEGY_TICK_FALLBACK_SECONDS")
    stale = _positive_number(env, "STRATEGY_TICK_STALE_SECONDS")
    try:
        return PriceTimeouts(
            poll_after=timedelta(seconds=poll) if poll else defaults.poll_after,
            stale_after=timedelta(seconds=stale) if stale else defaults.stale_after,
        )
    except ValueError as exc:
        raise SandboxConfigError(
            f"STRATEGY_TICK_FALLBACK_SECONDS must be less than STRATEGY_TICK_STALE_SECONDS: {exc}"
        ) from exc


def watch_list(env: Mapping[str, str]) -> list[tuple[str, Exchange]]:
    """`OPENTICKER_WATCH`: instruments to stream prices for even without a
    position, as EXCHANGE:SYMBOL pairs separated by commas, e.g.
    "NSE:NIFTY 50,NSE:RELIANCE"."""
    pairs: list[tuple[str, Exchange]] = []
    for entry in (env.get("OPENTICKER_WATCH") or "").split(","):
        if not entry.strip():
            continue
        exchange, _, symbol = entry.strip().partition(":")
        if not symbol or exchange not in Exchange.__members__:
            raise WatchConfigError(
                f"OPENTICKER_WATCH entries are EXCHANGE:SYMBOL (e.g. NSE:NIFTY 50), got {entry!r}"
            )
        pairs.append((symbol.strip(), Exchange(exchange)))
    return pairs


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
