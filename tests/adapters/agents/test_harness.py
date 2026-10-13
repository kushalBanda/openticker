import json
import time
from pathlib import Path

import pytest

from openticker.adapters.agents.harness import (
    HarnessProcesses,
    command,
    job_env,
    read_outcome,
    stdin_text,
)
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
        "events_path": tmp_path / "job_1.events.jsonl",
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
    events = tmp_path / "e"
    events.write_text(
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "result": "keep: net 1,200",
                "total_cost_usd": 0.41,
                "session_id": "sess-1",
            }
        )
    )

    outcome = read_outcome(Harness.CLAUDE, events, tmp_path / "unused")

    assert (outcome.summary, outcome.cost_usd) == ("keep: net 1,200", 0.41)
    assert outcome.session_id == "sess-1"
    missing = tmp_path / "missing"
    assert read_outcome(Harness.CLAUDE, missing, missing).summary is None


def test_a_codex_answer_is_its_last_message(tmp_path: Path) -> None:
    result = tmp_path / "r"
    result.write_text("retire: the test is met\n")

    assert read_outcome(Harness.CODEX, tmp_path / "e", result).summary == "retire: the test is met"


def test_a_real_process_gets_the_clean_environment(tmp_path: Path) -> None:
    fake = tmp_path / "bin" / "claude"
    fake.parent.mkdir()
    fake.write_text(
        "#!/bin/sh\n"
        'env > "$HOME/env.txt"\n'
        'echo \'{"type": "result", "subtype": "success", "result": "keep"}\'\n'
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
    assert processes.outcome(Harness.CLAUDE, launch.events_path, launch.result_path).summary == (
        "keep"
    )
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


def test_review_command_streams_events_with_its_model_effort_and_cap(tmp_path: Path) -> None:
    argv = command(
        _launch(tmp_path, model="opus", effort="high", max_budget_usd=2.0), "/bin/claude"
    )

    assert argv[:3] == ["/bin/claude", "-p", "Review it. (OpenTicker agent job job_1)"]
    assert argv[argv.index("--agent") + 1] == "reviewer"
    assert argv[argv.index("--model") + 1] == "opus"
    assert argv[argv.index("--effort") + 1] == "high"
    assert argv[argv.index("--output-format") + 1 :][:2] == ["stream-json", "--verbose"]
    assert argv[argv.index("--max-budget-usd") + 1] == "2"


def _chat(tmp_path: Path, **kw: object) -> AgentLaunch:
    fields: dict[str, object] = {
        "prompt": "--why did expiry days lose?",
        "agent": None,
        "context": "From the web app. (OpenTicker agent job job_1)",
    }
    fields.update(kw)
    harness = fields.pop("harness", Harness.CLAUDE)
    assert isinstance(harness, Harness)
    return _launch(tmp_path, harness, **fields)


def test_claude_chat_command_resumes_with_model_effort_and_context(tmp_path: Path) -> None:
    argv = command(
        _chat(tmp_path, resume_session="sess-1", model="opus", effort="high"), "/bin/claude"
    )

    assert argv[argv.index("--resume") + 1] == "sess-1"
    assert argv[argv.index("--model") + 1] == "opus"
    assert argv[argv.index("--effort") + 1] == "high"
    assert argv[argv.index("--append-system-prompt") + 1].endswith("agent job job_1)")
    assert argv[argv.index("--output-format") + 1 :][:2] == ["stream-json", "--verbose"]
    assert "--agent" not in argv
    assert "Write(notes/**)" in argv[argv.index("--allowedTools") + 1]
    assert not any("expiry days" in part for part in argv)  # the message goes on stdin


def test_claude_first_chat_turn_has_no_resume_and_the_harness_defaults(tmp_path: Path) -> None:
    argv = command(_chat(tmp_path), "/bin/claude")

    assert not {"--resume", "--model", "--effort"} & set(argv)


def test_a_chat_message_reaches_claude_on_stdin_and_events_go_to_their_file(
    tmp_path: Path,
) -> None:
    fake = tmp_path / "bin" / "claude"
    fake.parent.mkdir()
    fake.write_text(
        "#!/bin/sh\n"
        'printf \'{"type": "user_said", "text": "%s"}\\n\' "$(cat)"\n'
        'echo \'{"type": "result", "subtype": "success", "result": "ok", "session_id": "s"}\'\n'
    )
    fake.chmod(0o755)
    processes = HarnessProcesses({**PARENT, "PATH": f"{fake.parent}:/usr/bin:/bin"})
    launch = _chat(tmp_path)

    pid = processes.start(launch)
    deadline = time.monotonic() + 10
    while processes.poll(pid) is None and time.monotonic() < deadline:
        time.sleep(0.05)

    first = json.loads(launch.events_path.read_text().splitlines()[0])
    assert first["text"] == "--why did expiry days lose?"
    outcome = processes.outcome(Harness.CLAUDE, launch.events_path, launch.result_path)
    assert (outcome.summary, outcome.session_id) == ("ok", "s")


def test_detect_reads_versions_and_reports_a_missing_cli(tmp_path: Path) -> None:
    from openticker.adapters.agents.harness import detect
    from openticker.ports.agent_job_port import HarnessInfo

    claude = tmp_path / "claude"
    claude.write_text("#!/bin/sh\necho '2.1.296 (Claude Code)'\n")
    claude.chmod(0o755)

    found = detect({"PATH": str(tmp_path), "HOME": str(tmp_path)}, fresh=True)

    assert found == [
        HarnessInfo(Harness.CLAUDE, True, "2.1.296"),
        HarnessInfo(Harness.CODEX, False),
    ]


def test_codex_chat_command_resumes_with_model_effort_and_its_context_as_the_prompt(
    tmp_path: Path,
) -> None:
    launch = _chat(
        tmp_path, harness=Harness.CODEX, resume_session="thr-1", model="gpt-5.5", effort="minimal"
    )

    argv = command(launch, "/bin/codex")

    assert argv[:3] == ["/bin/codex", "exec", "--json"]
    assert argv[argv.index("-m") + 1] == "gpt-5.5"
    overrides = [argv[i + 1] for i, part in enumerate(argv) if part == "-c"]
    assert 'model_reasoning_effort="minimal"' in overrides
    # Options first, then `resume <id>`, then the prompt: the context, which names the job.
    assert argv[-3:] == ["resume", "thr-1", "From the web app. (OpenTicker agent job job_1)"]
    assert argv[argv.index("--sandbox") + 1] == "workspace-write"
    assert not any("expiry days" in part for part in argv)  # the message goes on stdin
    assert stdin_text(launch) == "--why did expiry days lose?"


def test_codex_first_chat_turn_has_no_resume_and_the_harness_defaults(tmp_path: Path) -> None:
    argv = command(_chat(tmp_path, harness=Harness.CODEX), "/bin/codex")

    assert not {"resume", "-m"} & set(argv)
    assert not any(part.startswith("model_reasoning_effort") for part in argv)


def test_codex_review_command_streams_events_with_its_prompt(tmp_path: Path) -> None:
    launch = _launch(tmp_path, Harness.CODEX, model="gpt-5.5", effort="high")

    argv = command(launch, "/bin/codex")

    assert "--json" in argv and argv[-1] == "Review it. (OpenTicker agent job job_1)"
    assert argv[argv.index("--output-last-message") + 1] == str(launch.result_path)
    assert stdin_text(launch) is None


def test_a_codex_chat_turn_writes_its_events_and_answers_from_them(tmp_path: Path) -> None:
    fake = tmp_path / "bin" / "codex"
    fake.parent.mkdir()
    fake.write_text(
        "#!/bin/sh\n"
        'echo \'{"type":"thread.started","thread_id":"thr-9"}\'\n'
        'printf \'{"type":"item.completed","item":{"id":"i","type":"agent_message","text":"%s"}}\\n\' "$(cat)"\n'
        'echo \'{"type":"turn.completed","usage":{"input_tokens":10,"output_tokens":2}}\'\n'
        "echo progress >&2\n"
    )
    fake.chmod(0o755)
    processes = HarnessProcesses({**PARENT, "PATH": f"{fake.parent}:/usr/bin:/bin"})
    launch = _chat(tmp_path, harness=Harness.CODEX, prompt="why?")

    pid = processes.start(launch)
    deadline = time.monotonic() + 10
    while processes.poll(pid) is None and time.monotonic() < deadline:
        time.sleep(0.05)

    outcome = processes.outcome(Harness.CODEX, launch.events_path, launch.result_path)
    assert (outcome.summary, outcome.session_id) == ("why?", "thr-9")
    assert (outcome.input_tokens, outcome.output_tokens) == (10, 2)
    assert "progress" in launch.log_path.read_text()


def test_detect_lists_models_from_the_harness_itself(tmp_path: Path) -> None:
    from openticker.adapters.agents.harness import detect

    codex = tmp_path / "codex"
    catalog = {
        "models": [
            {"slug": "gpt-6-luna", "display_name": "GPT-6-Luna", "visibility": "list"},
        ]
    }
    codex.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = debug ]; then echo \'' + json.dumps(catalog) + "'; "
        "else echo 'codex-cli 0.162.1'; fi\n"
    )
    codex.chmod(0o755)

    _, found = detect({"PATH": str(tmp_path), "HOME": str(tmp_path)}, fresh=True)

    assert found.version == "0.162.1"
    assert [(m.id, m.name) for m in found.models] == [("gpt-6-luna", "GPT-6-Luna")]


def test_claudes_default_is_the_model_the_users_settings_name(tmp_path: Path) -> None:
    from openticker.adapters.agents.harness import detect

    claude = tmp_path / "claude"
    answer = {
        "type": "control_response",
        "response": {
            "request_id": "openticker-models",
            "response": {
                "models": [
                    {"value": "default", "displayName": "Default", "description": "Sonnet 5.5"},
                    {
                        "value": "opus",
                        "displayName": "Opus 5.5",
                        "resolvedModel": "claude-opus-5-5",
                    },
                ]
            },
        },
    }
    claude.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = --version ]; then echo "2.1.296 (Claude Code)"; '
        "else echo '" + json.dumps(answer) + "'; fi\n"
    )
    claude.chmod(0o755)
    config = tmp_path / "config"
    config.mkdir()
    env = {"PATH": str(tmp_path), "HOME": str(tmp_path), "CLAUDE_CONFIG_DIR": str(config)}

    plain, _ = detect(env, fresh=True)
    (config / "settings.json").write_text('{"model": "opus"}')
    configured, _ = detect(env, fresh=True)

    assert plain.default_model is not None and plain.default_model.about == "Sonnet 5.5"
    assert configured.default_model is not None
    assert (configured.default_model.name, configured.default_model.resolves_to) == (
        "Opus 5.5",
        "claude-opus-5-5",
    )
