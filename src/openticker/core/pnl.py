"""Who did it (ADR 35 in docs/adr): the `triggered_by` an order, trade or
audit entry records, read as one of a few sources the web app labels (You,
Claude, Codex, a strategy, an alert, a script, ...). And the account's P&L
by day (ADR 34).

`triggered_by` stays the record; the source is derived when read, so old
rows (plain "mcp") read as an agent without being rewritten.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, time
from enum import StrEnum


class Source(StrEnum):
    YOU = "you"  # the web app
    CLAUDE_CODE = "claude-code"
    CODEX = "codex"
    AGENT = "agent"  # another MCP client, or one from before clients were named
    STRATEGY = "strategy"
    ALERT = "alert"
    SCRIPT = "script"
    SCHEDULE = "schedule"
    REST = "rest"
    SYSTEM = "system"  # the server itself: square-off, settlement, recovery


@dataclass(frozen=True)
class Rule:
    """`triggered_by` equal to `text` (or, with `prefix`, starting with it)
    reads as `source`. The first rule that matches wins."""

    text: str
    source: Source
    prefix: bool = False


# In order: a named client's exact value comes before the "mcp:" prefix.
RULES = (
    Rule("ui", Source.YOU),
    Rule("mcp", Source.AGENT),  # before clients were named
    Rule("webhook", Source.ALERT),
    Rule("mcp:claude-code", Source.CLAUDE_CODE),
    Rule("mcp:codex", Source.CODEX),
    Rule("mcp:", Source.AGENT, prefix=True),
    Rule("review:", Source.AGENT, prefix=True),
    Rule("strategy:", Source.STRATEGY, prefix=True),
    Rule("alert:", Source.ALERT, prefix=True),
    Rule("script:", Source.SCRIPT, prefix=True),
    Rule("rest:", Source.REST, prefix=True),
    Rule("schedule", Source.SCHEDULE, prefix=True),
)


def source_of(triggered_by: str | None) -> Source:
    """What no rule matches (or nothing recorded) is the server itself.
    Storage filters by source with the same `RULES`."""
    if triggered_by is None:
        return Source.SYSTEM
    if triggered_by.startswith("mcp:"):
        triggered_by = "mcp:" + client_name(triggered_by.removeprefix("mcp:"))
    for rule in RULES:
        if triggered_by == rule.text or (rule.prefix and triggered_by.startswith(rule.text)):
            return rule.source
    return Source.SYSTEM


def client_name(name: str) -> str:
    """An MCP client's name as `triggered_by` records it: lower case, spaces
    as hyphens ("Claude Code" and "claude-code" are one client)."""
    return "-".join(name.strip().lower().split())


# The account's P&L by day (ADR 34 in docs/adr). A day's figure is how much
# the paper account's equity moved since the last recorded close: what fills
# closed that day, less their charges, plus what open positions are worth now
# over what they were worth at that close. The web app's Today, the intraday
# line and the daily record all read it the same way.


@dataclass(frozen=True)
class DayFill:
    realized_pnl: float | None  # None: filled before it was recorded
    charges: float | None  # None: filled before costs were modelled


@dataclass(frozen=True)
class DayFigures:
    realized_pnl: float  # closed by the day's fills, before charges
    charges: float
    fills: int
    unrealized_pnl: (
        float | None
    )  # open positions' change since the last close; None: one has no price
    complete: bool  # every fill recorded what it realized

    @property
    def before_charges(self) -> float | None:
        if self.unrealized_pnl is None:
            return None
        return round(self.realized_pnl + self.unrealized_pnl, 2)

    @property
    def net_pnl(self) -> float | None:
        before = self.before_charges
        return None if before is None else round(before - self.charges, 2)


def day_figures(
    fills: Sequence[DayFill], open_pnl: Sequence[float | None], carried: float
) -> DayFigures:
    """`open_pnl`: each open position's unrealized P&L now. `carried`: what
    open positions were worth at the last recorded close (0 without one)."""
    marked = None if any(pnl is None for pnl in open_pnl) else sum(p or 0.0 for p in open_pnl)
    return DayFigures(
        realized_pnl=round(sum(f.realized_pnl or 0.0 for f in fills), 2),
        charges=round(sum(f.charges or 0.0 for f in fills), 2),
        fills=len(fills),
        unrealized_pnl=None if marked is None else round(marked - carried, 2),
        complete=all(f.realized_pnl is not None for f in fills),
    )


@dataclass(frozen=True)
class DayPnl:
    """One trading day, recorded after its close."""

    trading_date: date
    realized_pnl: float
    charges: float
    unrealized_pnl: float | None  # open positions' change over the day
    net_pnl: float | None  # after charges
    open_value: (
        float | None
    )  # open positions' unrealized P&L at the close: the next day's `carried`
    fills: int
    complete: bool
    estimated: bool = False  # closing marks were the last prices known, not live


def day_pnl(
    trading_date: date, figures: DayFigures, open_value: float | None, estimated: bool = False
) -> DayPnl:
    return DayPnl(
        trading_date=trading_date,
        realized_pnl=figures.realized_pnl,
        charges=figures.charges,
        unrealized_pnl=figures.unrealized_pnl,
        net_pnl=figures.net_pnl,
        open_value=open_value,
        fills=figures.fills,
        complete=figures.complete,
        estimated=estimated,
    )


@dataclass(frozen=True)
class IntradayPoint:
    minute: time  # exchange-local, in the session
    net_pnl: float  # after charges
    realized_pnl: float
    charges: float
    unrealized_pnl: float
