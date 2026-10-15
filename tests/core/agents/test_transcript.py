import json
from datetime import UTC, datetime
from pathlib import Path

from openticker.core.agents.jobs import Harness
from openticker.core.agents.transcript import (
    MAX_RESULT_CHARS,
    StepKind,
    Usage,
    own_usage,
    read_outcome,
    read_steps,
    session_gone,
)

FIXTURES = Path(__file__).parents[2] / "fixtures" / "transcripts"


def _lines(name: str) -> list[str]:
    return (FIXTURES / name).read_text().splitlines()


def test_claude_steps_in_order_with_results_paired() -> None:
    steps = read_steps(Harness.CLAUDE, _lines("claude_turn.jsonl"))

    assert [s.kind for s in steps] == [
        StepKind.THINKING,
        StepKind.TOOL,
        StepKind.TOOL,  # the subagent's call, its own words left out
        StepKind.EDIT,
        StepKind.TOOL,
        StepKind.TEXT,
    ]
    runs = steps[1]
    assert runs.tool == "get_strategy_runs"  # OpenTicker's prefix dropped
    assert runs.summary == "strategy_id=stg_ab12, limit=20"
    assert runs.result == '{"runs": 5, "expiry_days": 5, "lost": 4}'
    assert runs.at == datetime(2026, 10, 12, 6, 9, 2, 500_000, tzinfo=UTC)
    assert steps[2].result == "VIX opened 8% above its mean on 4 of 5 days"
    assert steps[3].tool == "Edit"
    assert steps[3].summary == "notes/NIFTY short straddle.md · +3 lines"
    assert steps[4].failed and steps[4].result == "broker session expired: reconnect"
    assert steps[-1].text == "Four of the five expiry-day losses came when INDIA VIX opened high."
    assert not any(s.text == "(a subagent's own words)" for s in steps)


def test_claude_outcome_names_session_model_tokens_cost_and_time() -> None:
    outcome = read_outcome(Harness.CLAUDE, _lines("claude_turn.jsonl"))

    assert outcome.session_id == "5f0c2a1e-8d3b-4c6a-9e7f-1a2b3c4d5e6f"
    assert outcome.answer == "Four of the five expiry-day losses came when INDIA VIX opened high."
    assert outcome.model_used == "claude-opus-5-5"  # more output tokens than the side model
    assert outcome.input_tokens == 10 + 16_000 + 20_000 + 200  # cached input counts
    assert outcome.output_tokens == 2_100 + 90
    assert outcome.cost_usd == 0.0712
    assert outcome.duration_ms == 41_000
    assert outcome.error is None


def test_a_resumed_turn_names_its_own_model_not_the_sessions_busiest() -> None:
    # Opus did the session's earlier turns; this one ran on Sonnet.
    lines = [
        json.dumps({"type": "system", "subtype": "init", "model": "claude-sonnet-5-5"}),
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "result": "ok",
                "total_cost_usd": 0.9,
                "modelUsage": {
                    "claude-opus-5-5": {"inputTokens": 50_000, "outputTokens": 3_000},
                    "claude-sonnet-5-5": {"inputTokens": 9_000, "outputTokens": 200},
                },
            }
        ),
    ]

    assert read_outcome(Harness.CLAUDE, lines).model_used == "claude-sonnet-5-5"


def test_own_usage_takes_off_the_previous_running_total() -> None:
    reported = Usage(0.45, 41_000, 800)

    assert own_usage(reported, Usage(0.30, 20_000, 500)) == Usage(0.15, 21_000, 300)


def test_own_usage_takes_a_new_session_or_a_missing_total_whole() -> None:
    reported = Usage(0.05, 9_000, 100)

    assert own_usage(reported, None) == reported
    assert own_usage(reported, Usage(0.30, 20_000, 500)) == reported  # went down: new session
    assert own_usage(reported, Usage(None, 2_000, None)) == Usage(0.05, 7_000, 100)


def test_claude_error_result_keeps_partial_steps_and_says_why() -> None:
    lines = _lines("claude_budget_error.jsonl")

    steps = read_steps(Harness.CLAUDE, lines)
    outcome = read_outcome(Harness.CLAUDE, lines)

    assert [s.kind for s in steps] == [StepKind.TEXT, StepKind.ERROR]
    assert steps[-1].text == "it reached its spend cap and stopped"
    assert outcome.error == "it reached its spend cap and stopped"
    assert outcome.answer == "Looking at the ledger."  # what it said before it stopped
    assert outcome.model_used == "claude-opus-5-5"  # from the init line
    assert (outcome.input_tokens, outcome.output_tokens) == (5, 40)


def test_review_json_output_reads_the_same() -> None:
    line = json.dumps(
        {"type": "result", "subtype": "success", "result": "keep", "total_cost_usd": 0.4}
    )

    outcome = read_outcome(Harness.CLAUDE, [line])

    assert (outcome.answer, outcome.cost_usd) == ("keep", 0.4)


def test_partial_last_line_and_unknown_events_are_skipped() -> None:
    lines = _lines("claude_turn.jsonl")[:6]
    lines += ['{"type": "assistant", "message": {"content": [{"type": "te', "not json", "[]"]
    lines += [json.dumps({"type": "something_new", "x": 1})]

    steps = read_steps(Harness.CLAUDE, lines)
    outcome = read_outcome(Harness.CLAUDE, lines)

    assert [s.kind for s in steps] == [StepKind.THINKING, StepKind.TOOL]
    assert outcome.answer is None and outcome.cost_usd is None
    assert outcome.session_id == "5f0c2a1e-8d3b-4c6a-9e7f-1a2b3c4d5e6f"


def test_long_tool_result_is_cut() -> None:
    lines = [
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "id": "t",
                            "name": "Read",
                            "input": {"file_path": "notes/a.md"},
                        }
                    ]
                },
            }
        ),
        json.dumps(
            {
                "type": "user",
                "message": {
                    "content": [{"type": "tool_result", "tool_use_id": "t", "content": "x" * 5_000}]
                },
            }
        ),
    ]

    (step,) = read_steps(Harness.CLAUDE, lines)

    assert step.result is not None and len(step.result) == MAX_RESULT_CHARS
    assert step.result.endswith("…")
    assert step.summary == "notes/a.md"


def test_codex_steps_each_item_once_as_last_reported() -> None:
    steps = read_steps(Harness.CODEX, _lines("codex_turn.jsonl"))

    assert [(s.kind, s.tool) for s in steps] == [
        (StepKind.THINKING, None),
        (StepKind.TOOL, "get_strategy_runs"),
        (StepKind.TOOL, "shell"),
        (StepKind.EDIT, "edit"),
        (StepKind.TEXT, None),
    ]  # the todo list isn't a step
    _, call, shell, edit, text = steps
    assert call.summary == "strategy_id=stg_ab12, limit=20"
    assert call.result == '{"runs": 5, "expiry_days": 5, "lost": 4}'
    assert (shell.summary, shell.result, shell.failed) == (
        "bash -lc 'ls notes'",
        "NIFTY short straddle.md\n",
        False,
    )
    assert edit.summary == "notes/NIFTY short straddle.md (update)"
    assert text.text == "Four of the five expiry-day losses came when INDIA VIX opened high."


def test_codex_outcome_session_answer_and_tokens_but_no_model_or_cost() -> None:
    outcome = read_outcome(Harness.CODEX, _lines("codex_turn.jsonl"))

    assert outcome.session_id == "0199a213-81c0-7800-8aa1-bbab2a035a53"
    assert outcome.answer == "Four of the five expiry-day losses came when INDIA VIX opened high."
    assert (outcome.input_tokens, outcome.output_tokens) == (24_763, 122)
    assert (outcome.model_used, outcome.cost_usd, outcome.error) == (None, None, None)


def test_codex_failed_turn_says_why_and_skips_the_partial_line() -> None:
    lines = _lines("codex_failed.jsonl")

    steps = read_steps(Harness.CODEX, lines)
    outcome = read_outcome(Harness.CODEX, lines)

    assert [s.kind for s in steps] == [StepKind.TOOL, StepKind.ERROR, StepKind.ERROR]
    assert steps[0].failed  # exit code 1
    assert outcome.error == "stream disconnected before completion"
    assert (outcome.input_tokens, outcome.answer) == (None, None)
    assert outcome.session_id == "0199a213-81c0-7800-8aa1-bbab2a035a54"


def test_a_conversation_that_cant_be_resumed_is_told_apart() -> None:
    assert session_gone("No conversation found with session ID: 5f0c2a1e")
    assert session_gone("thread 0199a213 not found")
    assert not session_gone("it reached its spend cap and stopped")
    assert not session_gone(None)
