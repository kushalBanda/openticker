import pytest

from openticker.core.pnl import Source, client_name, source_of


@pytest.mark.parametrize(
    ("triggered_by", "source"),
    [
        ("ui", Source.YOU),
        ("mcp:claude-code", Source.CLAUDE_CODE),
        ("mcp:codex", Source.CODEX),
        ("mcp:cursor", Source.AGENT),
        ("mcp", Source.AGENT),  # before clients were named
        ("review:s1", Source.AGENT),
        ("strategy:s1", Source.STRATEGY),
        ("webhook", Source.ALERT),
        ("alert:s1", Source.ALERT),
        ("script:abc", Source.SCRIPT),
        ("schedule", Source.SCHEDULE),
        ("schedule: every 5 runs", Source.SCHEDULE),
        ("rest:laptop", Source.REST),
        ("square-off", Source.SYSTEM),
        ("expiry-settlement", Source.SYSTEM),
        ("daemon", Source.SYSTEM),
        (None, Source.SYSTEM),
    ],
)
def test_source_of_maps_every_known_trigger(triggered_by: str | None, source: Source) -> None:
    assert source_of(triggered_by) == source


def test_client_names_are_one_spelling() -> None:
    assert client_name(" Claude Code ") == "claude-code"
    assert source_of("mcp:" + client_name("Codex")) == Source.CODEX
