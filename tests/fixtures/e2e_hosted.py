"""The Scripts and Agents mocks for the web app's end-to-end tests: three
hosted scripts with today's and yesterday's runs, the MCP clients seen,
review jobs besides the ones `e2e_strategies` seeds, and one chat about the
straddle whose turn is the recorded transcript in tests/fixtures/transcripts/.

rel_trail.py is real: started from the page, openticker-serve runs it with
its own key, and it prints RELIANCE's price from the REST API twice a
second, so its log grows while the page follows it. Its scheduled run for
today already ended, so the schedule doesn't start it again.
"""

from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path

from openticker.core.agents.jobs import AgentJobEndReason, AgentJobKind, Harness
from openticker.core.agents.threads import Folder
from openticker.core.scripts.models import ScriptSchedule, ScriptStopReason
from openticker.ports.agent_job_port import AgentOutcome
from openticker.ports.models import EXCHANGE_TIMEZONE
from openticker.storage import agent_job_files, script_files
from openticker.storage.sqlite import agent_jobs_repo, scripts_repo
from openticker.storage.sqlite.agent_clients_repo import note_client
from openticker.storage.sqlite.models import AgentThreadRow
from openticker.storage.sqlite.strategies_repo import write_transaction
from openticker.use_cases.scripts.manage import schedule_script, upload_script

REL_TRAIL = '''"""Trails a stop under the RELIANCE position."""

import json
import os
import time
import urllib.request

URL = os.environ["OPENTICKER_URL"]
KEY = os.environ["OPENTICKER_API_KEY"]


def get(path):
    request = urllib.request.Request(URL + path, headers={"X-API-Key": KEY})
    with urllib.request.urlopen(request, timeout=5) as response:
        return json.load(response)


print("watching RELIANCE; trigger 2,915.00")
while True:
    quote = get("/api/v1/quote?broker=fake&symbol=RELIANCE&exchange=NSE")
    print(f"RELIANCE {quote['last_price']:,.2f}, trigger stays 2,915.00")
    time.sleep(0.5)
'''

GAP_SCANNER = '''"""Lists the NIFTY 50 stocks that opened more than 1% away from yesterday's close."""

print("no gaps over 1% today")
'''

SCALP = '''"""Scalps BANKNIFTY futures on one-minute breakouts."""

bars = []
while True:
    bars.append([0.0] * 100_000)  # keeps every bar it has seen
'''


def _local(now: datetime, days: int, hour: int, minute: int, second: int = 0) -> datetime:
    day = now.astimezone(EXCHANGE_TIMEZONE) - timedelta(days=days)
    return day.replace(hour=hour, minute=minute, second=second, microsecond=0)


def _run(
    script_id: str,
    trigger: str,
    started: datetime,
    took: timedelta,
    reason: ScriptStopReason,
    detail: str,
    exit_code: int | None,
    peak_mb: int,
    lines: list[str],
) -> None:
    with write_transaction() as session:
        run = scripts_repo.add_run(session, script_id, trigger, started)
        scripts_repo.raise_peak_memory(session, {run.id: peak_mb * 1024})
        scripts_repo.end_run(session, run.id, reason, detail, exit_code, started + took)
    local = started.astimezone(EXCHANGE_TIMEZONE)
    script_files.append_log(
        script_id, run.id, f"=== run {run.id} started {local:%Y-%m-%d %H:%M:%S %Z} by {trigger} ==="
    )
    for line in lines:
        script_files.append_log(script_id, run.id, line)
    script_files.append_log(script_id, run.id, f"=== run {run.id} ended: {reason}, {detail} ===")


def seed_scripts(trail_id: str, clock: Callable[[], datetime]) -> None:
    """rel_trail.py was uploaded by the caller (its stop is in the book)."""
    now = clock()
    schedule_script(
        trail_id, ScriptSchedule(_local(now, 0, 9, 16).time(), _local(now, 0, 15, 15).time())
    )
    _run(
        trail_id,
        "schedule",
        _local(now, 0, 9, 16),
        timedelta(minutes=42),
        ScriptStopReason.STOPPED,
        "stop_script",
        -15,
        84,
        [
            "watching RELIANCE; trigger 2,915.00",
            "RELIANCE 2,931.50, trigger stays 2,915.00",
        ],
    )

    gaps = upload_script("gap_scanner.py", GAP_SCANNER, now)
    schedule_script(gaps.id, ScriptSchedule(_local(now, 0, 9, 10).time()))
    _run(
        gaps.id,
        "schedule",
        _local(now, 0, 9, 10),
        timedelta(seconds=42),
        ScriptStopReason.EXITED,
        "exited with code 0",
        0,
        61,
        ["no gaps over 1% today"],
    )

    scalp = upload_script("banknifty_scalp.py", SCALP, now)
    _run(
        scalp.id,
        "mcp:claude-code",
        _local(now, 1, 10, 2),
        timedelta(minutes=3, seconds=11),
        ScriptStopReason.MEMORY_LIMIT,
        "used 257 MB, over its 256 MB limit; killed by SIGKILL",
        -9,
        257,
        [],
    )


def seed_agents(strategies: dict[str, str], clock: Callable[[], datetime]) -> None:
    """Claude Code and Codex seen today; a review waiting and one timed out."""
    now = clock()
    note_client("claude-code", "stdio", "2.1.4", 212, now - timedelta(minutes=2), "get_positions")
    note_client("codex", "stdio", "0.41.0", 18, now - timedelta(minutes=48), "place_order")

    with write_transaction() as session:
        agent_jobs_repo.add_job(
            session,
            AgentJobKind.REVIEW,
            strategies["RELIANCE breakout"],
            Harness.CLAUDE,
            "ui",
            now - timedelta(minutes=1),
        )
        condor = agent_jobs_repo.add_job(
            session,
            AgentJobKind.REVIEW,
            strategies["BANKNIFTY iron condor"],
            Harness.CODEX,
            "mcp:codex",
            _local(now, 4, 11, 20),
        )
        agent_jobs_repo.mark_running(session, condor.id, 4242, _local(now, 4, 11, 20))
        agent_jobs_repo.end_job(
            session,
            condor.id,
            AgentJobEndReason.TIMEOUT,
            "still running after 15 minutes; killed by SIGKILL",
            _local(now, 4, 11, 35),
            exit_code=-9,
        )


CHAT_ID = "thr_e2e"
GONE_ID = "thr_gone"  # its session is one Claude Code no longer has
_TRANSCRIPT = Path(__file__).parent / "transcripts" / "claude_turn.jsonl"


def seed_chat(straddle_id: str, clock: Callable[[], datetime]) -> None:
    """ "Why did expiry days lose?", in the straddle's folder: one turn that
    ended, its steps and what ran read from the recorded transcript."""
    asked = clock() - timedelta(minutes=30)
    naive = asked.replace(tzinfo=None) - (asked.utcoffset() or timedelta())
    with write_transaction() as session:
        session.add(
            AgentThreadRow(
                id=CHAT_ID,
                title="Why did expiry days lose?",
                folder=Folder.STRATEGY.value,
                subject=straddle_id,
                harness=Harness.CLAUDE.value,
                session_id="5f0c2a1e-8d3b-4c6a-9e7f-1a2b3c4d5e6f",
                created_at=naive,
                updated_at=naive,
            )
        )
        turn = agent_jobs_repo.add_job(
            session,
            AgentJobKind.CHAT,
            None,
            Harness.CLAUDE,
            "ui",
            asked,
            thread_id=CHAT_ID,
            prompt="The review says skip expiry days. Why did they lose?",
            model="opus",
            effort="high",
        )
        agent_jobs_repo.mark_running(session, turn.id, 4343, asked)
        agent_jobs_repo.mark_outcome(
            session,
            turn.id,
            AgentOutcome(None, None, "5f0c2a1e", "claude-opus-5-5", 36_210, 2_190, 41_000),
        )
        agent_jobs_repo.end_job(
            session,
            turn.id,
            AgentJobEndReason.FINISHED,
            "exited with code 0",
            asked + timedelta(seconds=41),
            0,
            "Four of the five expiry-day losses came when INDIA VIX opened high.",
            0.07,
        )
    agent_job_files.events_path(turn.id).write_text(_TRANSCRIPT.read_text())


def seed_gone_chat(clock: Callable[[], datetime]) -> None:
    """ "An old chat", in General: one turn that ended, whose session
    tests/fixtures/fake_claude.py no longer has, so it can't be continued."""
    asked = clock() - timedelta(days=3)
    naive = asked.replace(tzinfo=None) - (asked.utcoffset() or timedelta())
    with write_transaction() as session:
        session.add(
            AgentThreadRow(
                id=GONE_ID,
                title="An old chat",
                folder=Folder.GENERAL.value,
                subject=None,
                harness=Harness.CLAUDE.value,
                session_id="gone-1a2b3c4d",
                created_at=naive,
                updated_at=naive,
            )
        )
        turn = agent_jobs_repo.add_job(
            session,
            AgentJobKind.CHAT,
            None,
            Harness.CLAUDE,
            "ui",
            asked,
            thread_id=GONE_ID,
            prompt="What was the desk's best day?",
        )
        agent_jobs_repo.mark_running(session, turn.id, 4344, asked)
        agent_jobs_repo.end_job(
            session,
            turn.id,
            AgentJobEndReason.FINISHED,
            "exited with code 0",
            asked + timedelta(seconds=20),
            0,
            "Tuesday the 6th: ₹4,210 after charges.",
        )
