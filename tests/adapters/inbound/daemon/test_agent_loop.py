from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from openticker.adapters.inbound.daemon import agent_loop
from openticker.adapters.inbound.daemon.agent_loop import REVIEW_CHECK_EVERY, AgentLoop
from openticker.core.agents.jobs import AgentJobEndReason, AgentSettings
from openticker.storage.sqlite import agent_jobs_repo
from openticker.use_cases.agents.manage import start_review
from openticker.use_cases.agents.supervise import AgentContext
from openticker.use_cases.strategies.define import create_strategy
from tests.fixtures.strategies import STRADDLE, list_nifty_market
from tests.use_cases.agents.test_agent_jobs import _Events, _Processes

NOW = datetime(2026, 9, 22, 4, 0, tzinfo=UTC)


def test_the_first_pass_ends_what_a_previous_daemon_left_then_starts_what_waits(
    tmp_path: Path,
) -> None:
    list_nifty_market()
    left = start_review(create_strategy("left", STRADDLE, NOW).id, AgentSettings(), "mcp", NOW)
    before = _Processes()
    AgentLoop(AgentContext(before, _Events(), AgentSettings(), tmp_path, "u"), lambda: NOW).step()
    waiting = start_review(create_strategy("next", STRADDLE, NOW).id, AgentSettings(), "mcp", NOW)
    after = _Processes()
    loop = AgentLoop(AgentContext(after, _Events(), AgentSettings(), tmp_path, "u"), lambda: NOW)

    loop.step()
    loop.step()

    lost = agent_jobs_repo.find_job(left.id)
    assert lost is not None and lost.end_reason is AgentJobEndReason.LOST
    assert [launch.job_id for launch in after.launches] == [waiting.id]


def test_schedules_are_checked_once_a_minute(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checks: list[datetime] = []
    monkeypatch.setattr(agent_loop, "queue_due_reviews", lambda context, now: checks.append(now))
    now = NOW
    loop = AgentLoop(
        AgentContext(_Processes(), _Events(), AgentSettings(), tmp_path, "u"), lambda: now
    )

    for _ in range(5):  # 0, 30, 60, 90 and 120 seconds in
        loop.step()
        now += timedelta(seconds=30)

    assert checks == [NOW, NOW + REVIEW_CHECK_EVERY, NOW + 2 * REVIEW_CHECK_EVERY]
