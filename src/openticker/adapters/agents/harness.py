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
import re
import shutil
import signal
import subprocess
import tempfile
import time
from collections.abc import Mapping
from pathlib import Path

from openticker.adapters.scripts.supervisor import alive, ps
from openticker.core.agents import transcript
from openticker.core.agents.jobs import Harness
from openticker.ports.agent_job_port import AgentLaunch, AgentOutcome, HarnessInfo
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

# Claude Code: its tools are the job's agent's; these rules let them run
# unattended. A reviewer writes under notes/ only; a debrief writes no file
# at all, only through OpenTicker's brain tools; it reads only its skill.
_CLAUDE_ALLOWED = "mcp__openticker,Read,Glob,Grep,Edit(notes/**),Write(notes/**)"
_CLAUDE_NO_FILES = "mcp__openticker,Read(.claude/skills/**)"


def job_env(api_key: str, parent: Mapping[str, str]) -> dict[str, str]:
    env = {name: parent[name] for name in (*_PASSED, *HARNESS_VARIABLES) if parent.get(name)}
    env.setdefault("PATH", os.defpath)
    env.setdefault("LANG", "C.UTF-8")
    env[KEY_VARIABLE] = api_key
    return env


def command(launch: AgentLaunch, executable: str) -> list[str]:
    """A chat's message isn't on the command line: it goes on stdin (`stdin_text`),
    where nothing reads it as an option and `ps` doesn't show it."""
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
        chat = launch.agent is None
        argv = [executable, "-p"] if chat else [executable, "-p", launch.prompt]
        if launch.agent is not None:
            argv += ["--agent", launch.agent]
        if launch.resume_session is not None:
            argv += ["--resume", launch.resume_session]
        if launch.model is not None:
            argv += ["--model", launch.model]
        if launch.effort is not None:
            argv += ["--effort", launch.effort]
        if launch.context is not None:
            argv += ["--append-system-prompt", launch.context]
        argv += [
            "--mcp-config",
            json.dumps(servers),
            "--strict-mcp-config",
            "--allowedTools",
            _CLAUDE_ALLOWED if launch.writes_notes else _CLAUDE_NO_FILES,
            # Every run's steps are read as they happen, and its last line
            # says what ran (ADR 40).
            "--output-format",
            "stream-json",
            "--verbose",
        ]
        if launch.max_budget_usd is not None:
            argv += ["--max-budget-usd", f"{launch.max_budget_usd:g}"]
        return argv
    job_server = f'{{url="{launch.mcp_url}", bearer_token_env_var="{KEY_VARIABLE}"}}'
    argv = [
        executable,
        "exec",
        "--json",  # its events on stdout, read as they happen (ADR 40)
        "--ignore-user-config",
        "--sandbox",
        "workspace-write" if launch.writes_notes else "read-only",
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
    ]
    if launch.model is not None:
        argv += ["-m", launch.model]
    if launch.effort is not None:
        argv += ["-c", f'model_reasoning_effort="{launch.effort}"']
    if launch.resume_session is not None:
        argv += ["resume", launch.resume_session]
    if launch.agent is not None:
        return [*argv, launch.prompt]
    # A chat: Codex has no system prompt to append to, so its context is the
    # prompt and the message, on stdin, is added to it. The context names the
    # job, so its process is recognised after a restart.
    return [*argv, launch.context or "-"]


def stdin_text(launch: AgentLaunch) -> str | None:
    """A chat turn's message, written to the harness's stdin."""
    return launch.prompt if launch.agent is None else None


class HarnessProcesses:
    def __init__(self, parent: Mapping[str, str] | None = None) -> None:
        self._parent = parent if parent is not None else os.environ
        self._children: dict[int, subprocess.Popen[bytes]] = {}

    def start(self, launch: AgentLaunch) -> int:
        env = job_env(launch.api_key, self._parent)
        executable = shutil.which(launch.harness.value, path=env["PATH"])
        if executable is None:
            raise FileNotFoundError(f"{launch.harness} is not on PATH ({env['PATH']})")
        # Both harnesses print their events on stdout; Codex also writes its
        # last message to the result file.
        text = stdin_text(launch)
        with (
            launch.log_path.open("ab") as log,
            launch.events_path.open("wb") as events,
            tempfile.TemporaryFile() as stdin,
        ):
            if text is not None:
                stdin.write(text.encode())
                stdin.seek(0)
            process = subprocess.Popen(
                command(launch, executable),
                cwd=launch.labs_dir,
                env=env,
                stdin=stdin if text is not None else subprocess.DEVNULL,
                stdout=events,
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

    def outcome(self, harness: Harness, events_path: Path, result_path: Path) -> AgentOutcome:
        return read_outcome(harness, events_path, result_path)


def read_outcome(harness: Harness, events_path: Path, result_path: Path) -> AgentOutcome:
    """What the agent answered, and what ran and cost as far as the harness
    says, from its events (core/agents/transcript.py). Codex's answer falls
    back to its result file, which a run from before events also has."""
    try:
        with events_path.open(errors="replace") as lines:
            turn = transcript.read_outcome(harness, lines)
    except FileNotFoundError:
        turn = transcript.TurnOutcome()
    answer = turn.answer
    if harness is Harness.CODEX and answer is None:
        try:
            answer = result_path.read_text(errors="replace").strip() or None
        except FileNotFoundError:
            pass
    return AgentOutcome(
        summary=answer if turn.error is None else turn.error,
        cost_usd=turn.cost_usd,
        session_id=turn.session_id,
        model_used=turn.model_used,
        input_tokens=turn.input_tokens,
        output_tokens=turn.output_tokens,
        duration_ms=turn.duration_ms,
        error=turn.error,
    )


DETECT_EVERY = 60.0  # seconds a detection is kept
_VERSION = re.compile(r"\d+\.\d+(?:\.\d+)?")
_detected: tuple[float, list[HarnessInfo]] | None = None


def detect(parent: Mapping[str, str] | None = None, *, fresh: bool = False) -> list[HarnessInfo]:
    """Which harnesses are on the PATH jobs get, and their versions: each
    `<cli> --version`, five seconds at most. Kept a minute."""
    global _detected
    if not fresh and _detected is not None and time.monotonic() - _detected[0] < DETECT_EVERY:
        return _detected[1]
    path = job_env("", parent if parent is not None else os.environ)["PATH"]
    found = [_detect_one(harness, path) for harness in Harness]
    _detected = (time.monotonic(), found)
    return found


def _detect_one(harness: Harness, path: str) -> HarnessInfo:
    executable = shutil.which(harness.value, path=path)
    if executable is None:
        return HarnessInfo(harness, installed=False)
    try:
        done = subprocess.run(
            [executable, "--version"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
            env={"PATH": path, "HOME": os.environ.get("HOME", "")},
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return HarnessInfo(harness, installed=True)
    version = _VERSION.search(done.stdout or "")
    return HarnessInfo(harness, installed=True, version=version.group(0) if version else None)
