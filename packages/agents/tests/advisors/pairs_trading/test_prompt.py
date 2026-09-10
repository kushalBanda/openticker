import json

from agents.advisors.pairs_trading.prompt import build_prompt
from agents.advisors.pairs_trading.schema import (
    CandidateStats,
    PairsTradingProposal,
    SelectedPairWeight,
)

_PRIOR = PairsTradingProposal(
    entry_z=2.0,
    formation_months=6,
    trading_months=3,
    buffer=0.1,
    selected=(SelectedPairWeight("A", "B", 0.9),),
)


def test_builds_system_and_user_messages() -> None:
    candidates = [
        CandidateStats(
            symbol_a="A", symbol_b="B", ssd=0.1, spread_mean=0.0, spread_std=0.02,
            realized_vol=0.15, correlation=0.92,
        )
    ]

    messages = build_prompt(candidates, _PRIOR)

    assert [m["role"] for m in messages] == ["system", "user"]
    user_payload = json.loads(messages[1]["content"])
    assert user_payload["candidate_window"][0]["symbol_a"] == "A"
    assert user_payload["prior_cycle_params"]["entry_z"] == 2.0


def test_omits_absent_performance_fields_for_new_pairs() -> None:
    candidates = [
        CandidateStats(
            symbol_a="A", symbol_b="B", ssd=0.1, spread_mean=0.0, spread_std=0.02,
            realized_vol=0.15, correlation=0.92,
        )
    ]

    messages = build_prompt(candidates, _PRIOR)
    payload = json.loads(messages[1]["content"])
    candidate = payload["candidate_window"][0]

    assert "win_rate" not in candidate
    assert "realized_pnl" not in candidate
    assert "trade_count" not in candidate


def test_includes_performance_fields_when_present() -> None:
    candidates = [
        CandidateStats(
            symbol_a="A", symbol_b="B", ssd=0.1, spread_mean=0.0, spread_std=0.02,
            realized_vol=0.15, correlation=0.92,
            win_rate=0.6, realized_pnl=1250.0, trade_count=5,
        )
    ]

    messages = build_prompt(candidates, _PRIOR)
    candidate = json.loads(messages[1]["content"])["candidate_window"][0]

    assert candidate["win_rate"] == 0.6
    assert candidate["realized_pnl"] == 1250.0
    assert candidate["trade_count"] == 5


def test_feedback_appended_on_retry() -> None:
    messages = build_prompt([], _PRIOR, feedback="entry_z 5.0 outside [1.5, 3.5]")
    assert "entry_z 5.0 outside" in messages[1]["content"]


def test_no_feedback_note_on_first_attempt() -> None:
    messages = build_prompt([], _PRIOR)
    assert "invalid" not in messages[1]["content"]
