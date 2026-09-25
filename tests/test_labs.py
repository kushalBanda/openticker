"""The labs/ folder both coding agents open (ADR 27 in docs/adr): each finds
OpenTicker's MCP server, the same skills, and instructions of its own, and
the user's research never gets committed."""

import asyncio
import json
import re
import subprocess
import tomllib
from pathlib import Path

import pytest

LABS = Path(__file__).resolve().parents[1] / "labs"
CLAUDE_SKILLS = LABS / ".claude" / "skills"
CODEX_SKILLS = LABS / ".agents" / "skills"
OPENTICKER_SERVER = {"command": "uv", "args": ["run", "--directory", "..", "openticker-mcp"]}


def _skills(root: Path) -> dict[str, str]:
    return {path.parent.name: path.read_text() for path in root.glob("*/SKILL.md")}


def test_claude_code_reaches_openticker() -> None:
    config = json.loads((LABS / ".mcp.json").read_text())

    assert config["mcpServers"]["openticker"] == OPENTICKER_SERVER


def test_codex_reaches_openticker_the_same_way() -> None:
    config = tomllib.loads((LABS / ".codex" / "config.toml").read_text())

    assert config["mcp_servers"]["openticker"] == OPENTICKER_SERVER


def test_the_server_command_runs_the_installed_entry_point() -> None:
    scripts = tomllib.loads((LABS.parent / "pyproject.toml").read_text())["project"]["scripts"]

    assert OPENTICKER_SERVER["args"][-1] in scripts


def test_every_skill_is_the_same_for_both_agents() -> None:
    claude, codex = _skills(CLAUDE_SKILLS), _skills(CODEX_SKILLS)

    assert claude, "labs ships at least one skill"
    assert claude == codex


@pytest.mark.parametrize("name", sorted(_skills(CLAUDE_SKILLS)))
def test_a_skill_names_itself_and_says_when_to_use_it(name: str) -> None:
    text = (CLAUDE_SKILLS / name / "SKILL.md").read_text()
    front = re.match(r"---\n(.*?)\n---\n", text, re.DOTALL)

    assert front, f"{name}: SKILL.md starts with frontmatter"
    fields = dict(line.split(": ", 1) for line in front.group(1).splitlines())
    assert fields["name"] == name
    assert "Use when" in fields["description"]


def test_claude_code_reads_the_same_instructions_as_codex() -> None:
    assert (LABS / "CLAUDE.md").read_text().strip() == "@AGENTS.md"


def test_the_repositorys_contributor_instructions_stay_out_of_labs() -> None:
    """Guards the setting; that Claude Code honours it was checked by hand
    with canary words in a parent CLAUDE.md and CLAUDE.local.md (ADR 27)."""
    settings = json.loads((LABS / ".claude" / "settings.json").read_text())

    assert "**/!(labs|.claude*)/CLAUDE.md" in settings["claudeMdExcludes"]


@pytest.mark.parametrize("folder", ["notes", "research"])
def test_the_users_research_is_never_committed(folder: str) -> None:
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", f"labs/{folder}/idea.md"], cwd=LABS.parent, check=False
    )

    assert ignored.returncode == 0


def _claude_reviewer() -> tuple[dict[str, str], str]:
    text = (LABS / ".claude" / "agents" / "reviewer.md").read_text()
    front = re.match(r"---\n(.*?)\n---\n(.*)", text, re.DOTALL)
    assert front, "reviewer.md starts with frontmatter"
    return dict(line.split(": ", 1) for line in front.group(1).splitlines()), front.group(2)


def _read_only_tools() -> set[str]:
    from openticker.adapters.inbound.mcp_server import mcp

    tools = asyncio.run(mcp.list_tools())
    return {t.name for t in tools if t.annotations and t.annotations.read_only_hint}


def test_the_reviewer_can_only_read_openticker() -> None:
    fields, _ = _claude_reviewer()
    tools = [tool.strip() for tool in fields["tools"].split(",")]
    openticker = {t.removeprefix("mcp__openticker__") for t in tools if "openticker" in t}

    assert "get_strategy_ledger" in openticker
    assert openticker <= _read_only_tools()
    assert not {t for t in tools if t.startswith("mcp__") and "openticker" not in t}


def test_both_reviewers_follow_their_own_copy_of_the_skill_with_the_same_tools() -> None:
    fields, body = _claude_reviewer()
    codex = tomllib.loads((LABS / ".codex" / "agents" / "reviewer.toml").read_text())
    claude_tools = {
        t.strip().removeprefix("mcp__openticker__")
        for t in fields["tools"].split(",")
        if "openticker" in t
    }
    server = codex["mcp_servers"]["openticker"]

    assert fields["name"] == codex["name"] == "reviewer"
    assert ".claude/skills/review-strategy/SKILL.md" in body
    assert ".agents/skills/review-strategy/SKILL.md" in codex["developer_instructions"]
    assert set(server["enabled_tools"]) == claude_tools
    assert {k: server[k] for k in ("command", "args")} == OPENTICKER_SERVER
