import json
import time
from pathlib import Path

import pytest

from openticker.adapters.agents.harness import HarnessProcesses, command, job_env, read_outcome
from openticker.core.agents.jobs import Harness
from openticker.ports.agent_job_port import AgentLaunch

PARENT = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/Users/someone",
    "LANG": "en_IN.UTF-8",
    "CLAUDE_CONFIG_DIR": "/Users/someone/.claude-work",
    "KITE_API_SECRET": "secret",
    "SLACK_WEBHOOK_URL": "https://hooks.slack.com/x",
    "SMTP_PASSWORD": "pw",
    "OPENTICKER_HOME": "/Users/someone/.openticker",
}


def _launch(tmp_path: Path, harness: Harness = Harness.CLAUDE, **kw: object) -> AgentLaunch:
    fields: dict[str, object] = {
        "job_id": "job_1",
        "harness": harness,
        "prompt": "Review it. (OpenTicker agent job job_1)",
        "labs_dir": tmp_path,
        "log_path": tmp_path / "job_1.log",
        "result_path": tmp_path / "job_1.result",
        "api_key": "otk_secret",
        "mcp_url": "http://127.0.0.1:8750/mcp",
    }
    fields.update(kw)
    return AgentLaunch(**fields)  # type: ignore[arg-type]


def test_the_environment_has_the_sign_in_and_the_key_and_nothing_else() -> None:
    env = job_env("otk_secret", PARENT)

    assert env == {
        "PATH": "/usr/bin:/bin",
        "HOME": "/Users/someone",  # where the harness keeps its sign-in
        "LANG": "en_IN.UTF-8",
        "CLAUDE_CONFIG_DIR": "/Users/someone/.claude-work",
        "OPENTICKER_API_KEY": "otk_secret",
    }


def test_claude_runs_the_reviewer_with_only_openticker_over_http(tmp_path: Path) -> None:
    argv = command(_launch(tmp_path, max_budget_usd=1.5), "/bin/claude")

    servers = json.loads(argv[argv.index("--mcp-config") + 1])["mcpServers"]
    assert servers == {
        "openticker": {
            "type": "http",
            "url": "http://127.0.0.1:8750/mcp",
            "headers": {"X-API-Key": "${OPENTICKER_API_KEY}"},  # from the environment
        }
    }
    assert "--strict-mcp-config" in argv  # the user's other servers are left out
    assert argv[argv.index("--agent") + 1] == "reviewer"
    assert "Write(notes/**)" in argv[argv.index("--allowedTools") + 1]
    assert argv[argv.index("--max-budget-usd") + 1] == "1.5"
    assert not any("otk_secret" in part for part in argv)  # the key never shows in ps


def test_codex_turns_labs_stdio_server_off_and_reaches_openticker_over_http(
    tmp_path: Path,
) -> None:
    argv = command(_launch(tmp_path, Harness.CODEX), "/bin/codex")

    overrides = [argv[i + 1] for i, part in enumerate(argv) if part == "-c"]
    assert 'mcp_servers.openticker={command="true", enabled=false}' in overrides
    assert (
        'mcp_servers.openticker_job={url="http://127.0.0.1:8750/mcp", '
        'bearer_token_env_var="OPENTICKER_API_KEY"}'
    ) in overrides
    assert "--ignore-user-config" in argv and "--max-budget-usd" not in argv
    assert not any("otk_secret" in part for part in argv)


def test_a_claude_answer_gives_its_result_and_cost(tmp_path: Path) -> None:
    result = tmp_path / "r"
    result.write_text(json.dumps({"result": "keep: net 1,200", "total_cost_usd": 0.41}))

    outcome = read_outcome(Harness.CLAUDE, result)

    assert (outcome.summary, outcome.cost_usd) == ("keep: net 1,200", 0.41)
    assert read_outcome(Harness.CLAUDE, tmp_path / "missing").summary is None


def test_a_codex_answer_is_its_last_message(tmp_path: Path) -> None:
    result = tmp_path / "r"
    result.write_text("retire: the test is met\n")

    assert read_outcome(Harness.CODEX, result).summary == "retire: the test is met"


def test_a_real_process_gets_the_clean_environment(tmp_path: Path) -> None:
    fake = tmp_path / "bin" / "claude"
    fake.parent.mkdir()
    fake.write_text(
        "#!/bin/sh\n"
        'env > "$HOME/env.txt"\n'
        'echo \'{"result": "keep", "total_cost_usd": 0.1}\'\n'
        "echo progress >&2\n"
    )
    fake.chmod(0o755)
    home = tmp_path / "home"
    home.mkdir()
    processes = HarnessProcesses(
        {**PARENT, "PATH": f"{fake.parent}:/usr/bin:/bin", "HOME": str(home)}
    )
    launch = _launch(tmp_path)

    pid = processes.start(launch)
    deadline = time.monotonic() + 10
    while (exited := processes.poll(pid)) is None and time.monotonic() < deadline:
        time.sleep(0.05)

    assert exited is not None and exited.returncode == 0
    seen = dict(
        line.split("=", 1) for line in (home / "env.txt").read_text().splitlines() if "=" in line
    )
    assert seen["OPENTICKER_API_KEY"] == "otk_secret"
    assert not {"KITE_API_SECRET", "SLACK_WEBHOOK_URL", "SMTP_PASSWORD", "OPENTICKER_HOME"} & set(
        seen
    )
    assert processes.outcome(Harness.CLAUDE, launch.result_path).summary == "keep"
    assert "progress" in launch.log_path.read_text()


def test_a_missing_harness_says_so(tmp_path: Path) -> None:
    processes = HarnessProcesses({"PATH": str(tmp_path), "HOME": str(tmp_path)})

    with pytest.raises(FileNotFoundError, match="claude is not on PATH"):
        processes.start(_launch(tmp_path))


def test_claude_debrief_command_has_no_file_tools(tmp_path: Path) -> None:
    argv = command(_launch(tmp_path, agent="debrief", writes_notes=False), "/bin/claude")

    assert argv[argv.index("--agent") + 1] == "debrief"
    allowed = argv[argv.index("--allowedTools") + 1].split(",")
    assert allowed == ["mcp__openticker", "Read(.claude/skills/**)"]  # its skill, no writes


def test_codex_debrief_runs_read_only_sandbox(tmp_path: Path) -> None:
    argv = command(_launch(tmp_path, Harness.CODEX, writes_notes=False), "/bin/codex")

    assert argv[argv.index("--sandbox") + 1] == "read-only"


def test_reviewer_command_unchanged(tmp_path: Path) -> None:
    claude = command(_launch(tmp_path), "/bin/claude")
    codex = command(_launch(tmp_path, Harness.CODEX), "/bin/codex")

    assert claude[claude.index("--agent") + 1] == "reviewer"
    assert claude[claude.index("--allowedTools") + 1] == (
        "mcp__openticker,Read,Glob,Grep,Edit(notes/**),Write(notes/**)"
    )
    assert codex[codex.index("--sandbox") + 1] == "workspace-write"
