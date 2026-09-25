"""Runs agent jobs with the user's own coding agent (ADR 29 in docs/adr):
`claude -p` or `codex exec`, headless, in `labs/`, signed in however the user
signed in.

The job reaches OpenTicker only over MCP on openticker-serve, with its own
key, whose scope decides what it may call. The user's other MCP servers are
left out. Its environment is built from nothing: the harness gets what it
needs to find its sign-in (the user's HOME and its own settings variables)
and never the daemon's broker, SMTP or Slack settings.
"""

import json
import os
import shutil
import signal
import subprocess
from collections.abc import Mapping
from pathlib import Path

from openticker.adapters.scripts.supervisor import alive, ps
from openticker.core.agents.jobs import Harness
from openticker.ports.agent_job_port import AgentLaunch, AgentOutcome
from openticker.ports.script_process_port import Exited

# Copied from the daemon's environment when set: what a harness needs to run
# as the user and find their sign-in. Nothing else is.
_PASSED = ("PATH", "LANG", "HOME", "USER", "LOGNAME", "TMPDIR")
HARNESS_VARIABLES = (
    "CLAUDE_CONFIG_DIR",
    "ANTHROPIC_API_KEY",
    "CODEX_HOME",
    "OPENAI_API_KEY",
    "CODEX_API_KEY",
)
KEY_VARIABLE = "OPENTICKER_API_KEY"

# Claude Code: its tools are the reviewer agent's; these rules let them run
# unattended. Writes are allowed under notes/ only.
_CLAUDE_ALLOWED = "mcp__openticker,Read,Glob,Grep,Edit(notes/**),Write(notes/**)"


def job_env(api_key: str, parent: Mapping[str, str]) -> dict[str, str]:
    env = {name: parent[name] for name in (*_PASSED, *HARNESS_VARIABLES) if parent.get(name)}
    env.setdefault("PATH", os.defpath)
    env.setdefault("LANG", "C.UTF-8")
    env[KEY_VARIABLE] = api_key
    return env


def command(launch: AgentLaunch, executable: str) -> list[str]:
    if launch.harness is Harness.CLAUDE:
        servers = {
            "mcpServers": {
                "openticker": {
                    "type": "http",
                    "url": launch.mcp_url,
                    "headers": {"X-API-Key": "${" + KEY_VARIABLE + "}"},
                }
            }
        }
        argv = [
            executable,
            "-p",
            launch.prompt,
            "--agent",
            "reviewer",
            "--mcp-config",
            json.dumps(servers),
            "--strict-mcp-config",
            "--allowedTools",
            _CLAUDE_ALLOWED,
            "--output-format",
            "json",
        ]
        if launch.max_budget_usd is not None:
            argv += ["--max-budget-usd", f"{launch.max_budget_usd:g}"]
        return argv
    job_server = f'{{url="{launch.mcp_url}", bearer_token_env_var="{KEY_VARIABLE}"}}'
    return [
        executable,
        "exec",
        "--ignore-user-config",
        "--sandbox",
        "workspace-write",
        "--skip-git-repo-check",
        "--cd",
        str(launch.labs_dir),
        # labs' own server runs over stdio with the user's full authority: off.
        "-c",
        'mcp_servers.openticker={command="true", enabled=false}',
        "-c",
        f"mcp_servers.openticker_job={job_server}",
        "--output-last-message",
        str(launch.result_path),
        launch.prompt,
    ]


class HarnessProcesses:
    def __init__(self, parent: Mapping[str, str] | None = None) -> None:
        self._parent = parent if parent is not None else os.environ
        self._children: dict[int, subprocess.Popen[bytes]] = {}

    def start(self, launch: AgentLaunch) -> int:
        env = job_env(launch.api_key, self._parent)
        executable = shutil.which(launch.harness.value, path=env["PATH"])
        if executable is None:
            raise FileNotFoundError(f"{launch.harness} is not on PATH ({env['PATH']})")
        # Claude Code prints its answer as JSON on stdout; Codex writes its
        # last message to the result file and its progress to stdout.
        claude = launch.harness is Harness.CLAUDE
        with (
            launch.log_path.open("ab") as log,
            (launch.result_path if claude else Path(os.devnull)).open("wb") as result,
        ):
            process = subprocess.Popen(
                command(launch, executable),
                cwd=launch.labs_dir,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=result if claude else log,
                stderr=log,
                start_new_session=True,  # its own process group, apart from the daemon's
            )
        self._children[process.pid] = process
        return process.pid

    def poll(self, pid: int) -> Exited | None:
        child = self._children.get(pid)
        if child is not None:
            returncode = child.poll()
            if returncode is None:
                return None
            del self._children[pid]
            return Exited(returncode)
        return None if alive(pid) else Exited(None)

    def is_job(self, pid: int, job_id: str) -> bool:
        for line in ps("pid=", "command="):
            found, _, text = line.strip().partition(" ")
            if found == str(pid):
                return f"agent job {job_id}" in text
        return False

    def stop(self, pid: int, force: bool) -> None:
        try:
            os.killpg(pid, signal.SIGKILL if force else signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass  # already gone

    def outcome(self, harness: Harness, result_path: Path) -> AgentOutcome:
        return read_outcome(harness, result_path)


def read_outcome(harness: Harness, result_path: Path) -> AgentOutcome:
    """What the agent answered, and what it cost when the harness says."""
    try:
        text = result_path.read_text(errors="replace")
    except FileNotFoundError:
        return AgentOutcome(None, None)
    if harness is Harness.CODEX:
        return AgentOutcome(text.strip() or None, None)
    try:
        answer = json.loads(text.strip().splitlines()[-1]) if text.strip() else {}
    except json.JSONDecodeError:
        return AgentOutcome(text.strip() or None, None)
    cost = answer.get("total_cost_usd")
    result = answer.get("result")
    return AgentOutcome(
        result if isinstance(result, str) else None,
        float(cost) if isinstance(cost, int | float) else None,
    )
