import json
from typing import Any

import pytest
from agents.advisors.pairs_trading.advisor import PairsTradingAdvisor
from agents.advisors.pairs_trading.schema import (
    CandidateStats,
    PairsTradingProposal,
    SelectedPairWeight,
)
from agents.llm.core.interfaces import LLMResponse

_PRIOR = PairsTradingProposal(
    entry_z=2.0,
    formation_months=6,
    trading_months=3,
    buffer=0.1,
    selected=(SelectedPairWeight("A", "B", 0.9),),
)

_CANDIDATES = [
    CandidateStats(
        symbol_a="A", symbol_b="B", ssd=0.1, spread_mean=0.0, spread_std=0.02,
        realized_vol=0.15, correlation=0.92,
    ),
    CandidateStats(
        symbol_a="C", symbol_b="D", ssd=0.2, spread_mean=0.0, spread_std=0.03,
        realized_vol=0.18, correlation=0.88,
    ),
]

_VALID_JSON = json.dumps(
    {
        "entry_z": 2.2,
        "formation_months": 6,
        "trading_months": 3,
        "buffer": 0.1,
        "selected": [{"symbol_a": "A", "symbol_b": "B", "weight": 0.9}],
    }
)


class _FakeLLM:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls: list[list[dict[str, str]]] = []

    async def acomplete(self, messages: list[dict[str, str]], **kwargs: Any) -> LLMResponse:
        self.calls.append(messages)
        content = self._responses.pop(0)
        return LLMResponse(content=content, model="fake", raw=None)


async def test_propose_returns_valid_llm_output() -> None:
    llm = _FakeLLM([_VALID_JSON])
    advisor = PairsTradingAdvisor(llm=llm)  # type: ignore[arg-type]

    proposal = await advisor.propose(_CANDIDATES, _PRIOR)

    assert proposal.entry_z == 2.2
    assert proposal.selected == (SelectedPairWeight("A", "B", 0.9),)
    assert len(llm.calls) == 1


async def test_propose_retries_once_then_succeeds() -> None:
    llm = _FakeLLM(["not json at all", _VALID_JSON])
    advisor = PairsTradingAdvisor(llm=llm)  # type: ignore[arg-type]

    proposal = await advisor.propose(_CANDIDATES, _PRIOR)

    assert proposal.entry_z == 2.2
    assert len(llm.calls) == 2
    # Second call's user message carries the retry feedback.
    assert "invalid" in llm.calls[1][1]["content"]


async def test_propose_falls_back_to_prior_after_two_bad_responses() -> None:
    llm = _FakeLLM(["not json at all", "still not json"])
    advisor = PairsTradingAdvisor(llm=llm)  # type: ignore[arg-type]

    proposal = await advisor.propose(_CANDIDATES, _PRIOR)

    assert proposal is _PRIOR
    assert len(llm.calls) == 2


async def test_propose_falls_back_on_out_of_bounds_field() -> None:
    bad_bounds = json.dumps(
        {
            "entry_z": 10.0,
            "formation_months": 6,
            "trading_months": 3,
            "buffer": 0.1,
            "selected": [{"symbol_a": "A", "symbol_b": "B", "weight": 0.9}],
        }
    )
    llm = _FakeLLM([bad_bounds, bad_bounds])
    advisor = PairsTradingAdvisor(llm=llm)  # type: ignore[arg-type]

    proposal = await advisor.propose(_CANDIDATES, _PRIOR)

    assert proposal is _PRIOR


async def test_propose_falls_back_when_pair_not_in_candidate_window() -> None:
    unknown_pair = json.dumps(
        {
            "entry_z": 2.0,
            "formation_months": 6,
            "trading_months": 3,
            "buffer": 0.1,
            "selected": [{"symbol_a": "X", "symbol_b": "Y", "weight": 0.9}],
        }
    )
    llm = _FakeLLM([unknown_pair, unknown_pair])
    advisor = PairsTradingAdvisor(llm=llm)  # type: ignore[arg-type]

    proposal = await advisor.propose(_CANDIDATES, _PRIOR)

    assert proposal is _PRIOR


@pytest.mark.parametrize("bad_response", ["", "{}", '{"entry_z": "not a number"}'])
async def test_propose_falls_back_on_various_malformed_responses(bad_response: str) -> None:
    llm = _FakeLLM([bad_response, bad_response])
    advisor = PairsTradingAdvisor(llm=llm)  # type: ignore[arg-type]

    proposal = await advisor.propose(_CANDIDATES, _PRIOR)

    assert proposal is _PRIOR
