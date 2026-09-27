from datetime import timedelta

import pytest

from openticker.core.agents.jobs import (
    MAX_SUMMARY_CHARS,
    AgentJobEndReason,
    AgentJobError,
    AgentSettings,
    Verdict,
    capped,
    exit_reason,
    review_prompt,
    verdict_of,
)


def test_how_a_job_ended_follows_its_exit_status() -> None:
    assert exit_reason(0) == (AgentJobEndReason.FINISHED, "exited with code 0")
    assert exit_reason(1) == (AgentJobEndReason.FAILED, "exited with code 1")
    assert exit_reason(-15) == (AgentJobEndReason.FAILED, "killed by SIGTERM")
    assert exit_reason(None)[0] is AgentJobEndReason.FAILED


def test_settings_refuse_what_cant_run() -> None:
    with pytest.raises(AgentJobError, match="at least a minute"):
        AgentSettings(timeout=timedelta(seconds=30))
    with pytest.raises(AgentJobError, match="at least 1"):
        AgentSettings(jobs_per_day=0)
    with pytest.raises(AgentJobError, match="above 0"):
        AgentSettings(max_budget_usd=0)


def test_a_review_prompt_names_the_strategy_its_note_and_the_job() -> None:
    prompt = review_prompt("nifty condor", "stg_1", "job_9", "mcp")

    assert "'nifty condor' (stg_1)" in prompt and "notes/nifty condor.md" in prompt
    assert "review-strategy" in prompt and "unattended" in prompt
    assert "schedule" not in prompt
    assert prompt.endswith("(OpenTicker agent job job_9)")


def test_a_scheduled_review_is_told_why_it_is_due() -> None:
    prompt = review_prompt("nifty condor", "stg_1", "job_9", "schedule: every 1d")

    assert "due on its review schedule: every 1d." in prompt


def test_a_long_answer_is_capped() -> None:
    long = capped("x" * (MAX_SUMMARY_CHARS + 50))

    assert long is not None and len(long) == MAX_SUMMARY_CHARS and long.endswith("…")
    assert capped("  keep  ") == "keep" and capped(None) is None


def test_a_reviews_verdict_is_read_from_the_start_of_its_summary() -> None:
    assert verdict_of("Keep. Net +21,904 over 118 runs.") is Verdict.KEEP
    assert verdict_of("**Change one thing**: exit by 11:00 on expiry.") is Verdict.CHANGE
    assert verdict_of("### 2026-09-23: retire\nNet is negative.") is Verdict.RETIRE
    assert verdict_of("Verdict: keep") is Verdict.KEEP
    assert verdict_of("Not yet: 6 of 10 runs after costs.") is Verdict.NOT_YET


def test_a_summary_without_a_verdict_has_none() -> None:
    assert verdict_of(None) is None
    assert verdict_of("The ledger could not be read.") is None
    assert verdict_of("Keeping an eye on it") is None
