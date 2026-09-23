"""Alerts arriving at a signal strategy's URL (ADR 24 in docs/adr). The token
in the URL is the credential: TradingView and ChartInk can't send a header.
Each alert is checked, recorded, and written as signal commands the daemon's
runner carries out within about a second; nothing here places an order.

The checks, in order: the token names a signal strategy (else 404, not
recorded, the same answer whether it never existed or was rotated); the
strategy's calls stay under SIGNALS_PER_MINUTE (else 429, not recorded, so a
flood can't fill the table); its kill switch is off; the caller's address is
in its allowlist; the body is a JSON object naming legs and actions the
strategy takes. Every call past the first two is recorded.
"""

import hashlib
import ipaddress
import json
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from openticker.core.strategies.models import SignalStrategySpec
from openticker.core.strategies.runs import CommandKind
from openticker.core.strategies.signals import SignalRefused, read_alert, window_note
from openticker.storage.sqlite import runs_repo, signals_repo, strategies_repo
from openticker.storage.sqlite.runs_repo import WEBHOOK_TRIGGER
from openticker.storage.sqlite.strategies_repo import write_transaction

logger = logging.getLogger(__name__)

SIGNALS_PER_MINUTE = 100  # calls to one strategy's URL
MAX_ALERT_BYTES = 16_384  # an alert is a few hundred bytes
TOKEN_PREFIX = "otw_"
_TOKEN = re.compile(TOKEN_PREFIX + r"[A-Za-z0-9_-]{16,128}")
_PAYLOAD_KEPT = 2_000  # characters of the body kept with the call
_SECRET_KEYS = ("token", "secret", "password", "apikey", "api_key", "auth", "signature")
_REDACTED = "[redacted]"


class SignalResult(StrEnum):
    ACCEPTED = "accepted"  # written as signal commands
    IGNORED = "ignored"  # understood, but its schedule takes nothing now
    REFUSED = "refused"  # doesn't fit the strategy; the message says why
    LOCKED = "locked"  # the kill switch is on
    FORBIDDEN = "forbidden"  # the caller's address isn't in the allowlist
    RATE_LIMITED = "rate_limited"
    UNKNOWN = "unknown"  # no signal strategy has this token


@dataclass(frozen=True)
class SignalOutcome:
    result: SignalResult
    message: str
    strategy_id: str | None = None
    command_ids: tuple[int, ...] = ()


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def accept_signal(token: str, client_ip: str | None, body: bytes, now: datetime) -> SignalOutcome:
    webhook = signals_repo.webhook_by_hash(token_hash(token)) if _TOKEN.fullmatch(token) else None
    stored = strategies_repo.find_strategy(webhook.strategy_id) if webhook else None
    if webhook is None or stored is None or not isinstance(stored.spec, SignalStrategySpec):
        return SignalOutcome(
            SignalResult.UNKNOWN, "unknown alert URL: it was never made, or has been rotated"
        )
    strategy_id, spec = stored.id, stored.spec

    if signals_repo.calls_since(strategy_id, now - timedelta(minutes=1)) >= SIGNALS_PER_MINUTE:
        logger.warning(
            "alerts for %s are over %d a minute; refusing", strategy_id, SIGNALS_PER_MINUTE
        )
        return SignalOutcome(
            SignalResult.RATE_LIMITED,
            f"more than {SIGNALS_PER_MINUTE} alerts in a minute; slow down",
            strategy_id,
        )

    def record(
        outcome: SignalOutcome, alert_format: str | None = None, payload: str | None = None
    ) -> SignalOutcome:
        signals_repo.record_call(
            strategy_id,
            now,
            client_ip,
            outcome.result.value,
            outcome.message,
            alert_format,
            payload,
            outcome.command_ids,
        )
        return outcome

    if stored.locked:
        return record(SignalOutcome(SignalResult.LOCKED, "locked by its kill switch", strategy_id))
    if not ip_allowed(client_ip, webhook.allowed_ips):
        return record(
            SignalOutcome(
                SignalResult.FORBIDDEN,
                f"{client_ip or 'an unknown address'} is not in this alert URL's allowlist",
                strategy_id,
            )
        )
    payload = _parse(body)
    if isinstance(payload, str):
        return record(SignalOutcome(SignalResult.REFUSED, payload, strategy_id))
    kept = _redacted(payload, token)
    try:
        alert = read_alert(payload, spec)
    except SignalRefused as exc:
        return record(SignalOutcome(SignalResult.REFUSED, str(exc), strategy_id), None, kept)

    notes: list[str] = []
    wanted = []
    for signal in alert.signals:
        why = window_note(spec.schedule, signal.action, now)
        if why is None:
            wanted.append(signal)
        else:
            notes.append(f"{signal.leg_id} {signal.action} ignored: {why}")
    if alert.skipped:
        notes.append(f"not legs of this strategy, skipped: {', '.join(alert.skipped)}")
    command_ids: list[int] = []
    with write_transaction() as session:
        current = strategies_repo.load_strategy(session, strategy_id)
        killed = current is None or current.locked  # while the alert was read
        for signal in [] if killed else wanted:
            command = runs_repo.add_command(
                session,
                strategy_id,
                CommandKind.SIGNAL,
                WEBHOOK_TRIGGER,
                now,
                broker=webhook.broker,
                leg_id=signal.leg_id,
                action=signal.action,
            )
            command_ids.append(command.id)
    if killed:
        return record(
            SignalOutcome(SignalResult.LOCKED, "locked by its kill switch", strategy_id),
            alert.format.value,
            kept,
        )
    queued = [f"{signal.leg_id} {signal.action} queued" for signal in wanted]
    return record(
        SignalOutcome(
            SignalResult.ACCEPTED if command_ids else SignalResult.IGNORED,
            "; ".join(queued + notes),
            strategy_id,
            tuple(command_ids),
        ),
        alert.format.value,
        kept,
    )


def ip_allowed(client_ip: str | None, allowed: tuple[str, ...]) -> bool:
    """An empty allowlist allows any address. Otherwise the caller must fall in
    one of its addresses or ranges; one that can't be read is refused."""
    if not allowed:
        return True
    try:
        address = ipaddress.ip_address((client_ip or "").strip())
    except ValueError:
        return False
    candidates = [address]
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        candidates.append(address.ipv4_mapped)  # an IPv4 caller seen through IPv6
    return any(
        candidate.version == network.version and candidate in network
        for network in (ipaddress.ip_network(entry, strict=False) for entry in allowed)
        for candidate in candidates
    )


def _parse(body: bytes) -> dict[str, object] | str:
    """The body as a JSON object, or why it isn't one."""
    if len(body) > MAX_ALERT_BYTES:
        return f"the body is larger than {MAX_ALERT_BYTES} bytes"
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return "the body is not JSON"
    if not isinstance(parsed, dict):
        return "the body must be a JSON object"
    return parsed


def _redacted(payload: dict[str, object], token: str) -> str:
    """The body as kept with the call: without the token (ChartInk sends the
    URL back in `webhook_url`) or anything named like a secret, capped."""

    def clean(value: object) -> object:
        if isinstance(value, dict):
            return {
                str(key): _REDACTED
                if any(hint in str(key).lower() for hint in _SECRET_KEYS)
                else clean(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, str) and (token in value or TOKEN_PREFIX in value):
            return _REDACTED
        return value

    return json.dumps(clean(payload))[:_PAYLOAD_KEPT]
