"""Alerts for signal strategies: what an alert asks for, whether the strategy
takes it, and what it does to the leg it names. Pure. Rules: ADR 24 in
docs/adr."""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from openticker.core.strategies.models import Schedule, SignalStrategySpec, leg_id
from openticker.ports.models import EXCHANGE_TIMEZONE, Side


class SignalAction(StrEnum):
    LONG_ENTRY = "long_entry"
    LONG_EXIT = "long_exit"
    SHORT_ENTRY = "short_entry"
    SHORT_EXIT = "short_exit"

    @property
    def long(self) -> bool:
        return self in (SignalAction.LONG_ENTRY, SignalAction.LONG_EXIT)

    @property
    def entry(self) -> bool:
        return self in (SignalAction.LONG_ENTRY, SignalAction.SHORT_ENTRY)

    @property
    def side(self) -> Side:
        """The side of the position it opens or closes."""
        return Side.BUY if self.long else Side.SELL


class AlertFormat(StrEnum):
    CHARTINK = "chartink"  # {"stocks": "A,B", "scan_name": "... BUY ...", ...}
    JSON = "json"  # {"action": "long_entry", "leg_id": "leg1"} or with "symbol"


class Move(StrEnum):
    ENTER = "enter"
    FLIP = "flip"  # close the opposite position, then enter
    EXIT = "exit"
    NONE = "none"  # nothing to do; not an error


@dataclass(frozen=True)
class Signal:
    leg_id: str
    action: SignalAction


@dataclass(frozen=True)
class Alert:
    format: AlertFormat
    signals: tuple[Signal, ...]
    skipped: tuple[str, ...] = ()  # ChartInk symbols that are none of the legs


class SignalRefused(ValueError):
    """The alert doesn't fit the strategy; the message says what to change."""


# ChartInk names the action in the scan's name: BUY and SHORT enter, SELL and
# COVER exit.
_CHARTINK_ACTIONS = {
    "BUY": SignalAction.LONG_ENTRY,
    "SELL": SignalAction.LONG_EXIT,
    "SHORT": SignalAction.SHORT_ENTRY,
    "COVER": SignalAction.SHORT_EXIT,
}
_WORD = re.compile(r"[A-Z]+")


def read_alert(payload: Mapping[str, object], spec: SignalStrategySpec) -> Alert:
    """The signals an alert carries, each for one of the strategy's legs.
    Raises SignalRefused when it names no leg, or asks for something the
    strategy's direction or the leg's `accepts` rules out."""
    if "stocks" in payload and "scan_name" in payload:
        alert = _chartink(payload, spec)
    else:
        alert = Alert(AlertFormat.JSON, (_json(payload, spec),))
    for signal in alert.signals:
        _check_side(spec, signal)
    return alert


def window_note(schedule: Schedule, action: SignalAction, now: datetime) -> str | None:
    """Why the schedule ignores this alert now, if it does. Entries are taken
    from `entry_time` on `weekdays`; nothing is taken from `exit_time`, which
    closes the day's run."""
    local = now.astimezone(EXCHANGE_TIMEZONE)
    if schedule.exit_time is not None and local.time() >= schedule.exit_time:
        return f"after exit_time {schedule.exit_time:%H:%M}"
    if not action.entry:
        return None
    if local.weekday() not in schedule.weekdays:
        return f"{local:%A} is not one of its weekdays"
    if schedule.entry_time is not None and local.time() < schedule.entry_time:
        return f"before entry_time {schedule.entry_time:%H:%M}"
    return None


def signal_move(action: SignalAction, held: Side | None) -> tuple[Move, str]:
    """What a signal does to a leg held on `held` (None: flat), and why.
    Alert senders repeat themselves, so an entry for a position already held
    and an exit for one that isn't do nothing rather than fail."""
    position = "long" if action.long else "short"
    if action.entry:
        if held is None:
            return Move.ENTER, f"entering {position}"
        if held is action.side:
            return Move.NONE, f"already {position}"
        return (
            Move.FLIP,
            f"closing the {'short' if action.long else 'long'}, then entering {position}",
        )
    if held is action.side:
        return Move.EXIT, f"exiting the {position}"
    return Move.NONE, f"no {position} position to exit"


def _chartink(payload: Mapping[str, object], spec: SignalStrategySpec) -> Alert:
    scan = str(payload.get("scan_name") or "").upper()
    named = {word for word in _WORD.findall(scan) if word in _CHARTINK_ACTIONS}
    if len(named) != 1:
        raise SignalRefused(
            f"the scan name {scan!r} must contain exactly one of BUY, SELL, SHORT or COVER, "
            "which says what the alert does"
        )
    action = _CHARTINK_ACTIONS[named.pop()]
    symbols = list(
        dict.fromkeys(
            symbol.strip().upper() for symbol in str(payload["stocks"]).split(",") if symbol.strip()
        )
    )
    signals, skipped = [], []
    for symbol in symbols:
        index = next((i for i, leg in enumerate(spec.legs) if leg.symbol.upper() == symbol), None)
        if index is None:
            skipped.append(symbol)
        else:
            signals.append(Signal(leg_id(index), action))
    if not signals:
        raise SignalRefused(
            f"none of {', '.join(symbols) or 'the stocks'} is a leg of this strategy; its legs "
            f"trade {_symbols(spec)}"
        )
    return Alert(AlertFormat.CHARTINK, tuple(signals), tuple(skipped))


def _json(payload: Mapping[str, object], spec: SignalStrategySpec) -> Signal:
    raw = payload.get("action")
    try:
        action = SignalAction(raw.strip().lower() if isinstance(raw, str) else "")
    except ValueError:
        raise SignalRefused(
            f"'action' must be one of {', '.join(action.value for action in SignalAction)}, "
            f"got {raw!r}"
        ) from None
    wanted = payload.get("leg_id")
    if wanted is not None:
        ids = [leg_id(i) for i in range(len(spec.legs))]
        if str(wanted) not in ids:
            raise SignalRefused(f"no leg {wanted!r}; this strategy's legs are {', '.join(ids)}")
        return Signal(str(wanted), action)
    symbol = str(payload.get("symbol") or "").strip().upper()
    exchange = str(payload.get("exchange") or "").strip().upper()
    if not symbol:
        raise SignalRefused("name the leg: give 'leg_id', or 'symbol' (and 'exchange')")
    for index, leg in enumerate(spec.legs):
        if leg.symbol.upper() == symbol and exchange in ("", leg.exchange.value):
            return Signal(leg_id(index), action)
    raise SignalRefused(f"no leg trades {symbol}; this strategy's legs trade {_symbols(spec)}")


def _check_side(spec: SignalStrategySpec, signal: Signal) -> None:
    position = "long" if signal.action.long else "short"
    if not spec.direction.allows(signal.action.long):
        raise SignalRefused(f"this strategy is {spec.direction}; a {position} alert is refused")
    leg = next(leg for i, leg in enumerate(spec.legs) if leg_id(i) == signal.leg_id)
    if not leg.accepts.allows(signal.action.long):
        raise SignalRefused(
            f"{signal.leg_id} accepts {leg.accepts} alerts; a {position} one is refused"
        )


def _symbols(spec: SignalStrategySpec) -> str:
    return ", ".join(f"{leg.symbol} ({leg.exchange})" for leg in spec.legs)
