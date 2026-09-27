"""Who did it (ADR 35 in docs/adr): the `triggered_by` an order, trade or
audit entry records, read as one of a few sources the web app labels (You,
Claude, Codex, a strategy, an alert, a script, ...).

`triggered_by` stays the record; the source is derived when read, so old
rows (plain "mcp") read as an agent without being rewritten.
"""

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


_CLIENTS = {"claude-code": Source.CLAUDE_CODE, "codex": Source.CODEX}

_PREFIXES = (
    ("mcp:", Source.AGENT),
    ("review:", Source.AGENT),
    ("strategy:", Source.STRATEGY),
    ("alert:", Source.ALERT),
    ("script:", Source.SCRIPT),
    ("rest:", Source.REST),
    ("schedule", Source.SCHEDULE),
)


def source_of(triggered_by: str | None) -> Source:
    if triggered_by is None:
        return Source.SYSTEM
    if triggered_by == "ui":
        return Source.YOU
    if triggered_by == "mcp":
        return Source.AGENT
    if triggered_by == "webhook":
        return Source.ALERT
    if triggered_by.startswith("mcp:"):
        return _CLIENTS.get(client_name(triggered_by.removeprefix("mcp:")), Source.AGENT)
    for prefix, source in _PREFIXES:
        if triggered_by.startswith(prefix):
            return source
    return Source.SYSTEM


def client_name(name: str) -> str:
    """An MCP client's name as `triggered_by` records it: lower case, spaces
    as hyphens ("Claude Code" and "claude-code" are one client)."""
    return "-".join(name.strip().lower().split())
