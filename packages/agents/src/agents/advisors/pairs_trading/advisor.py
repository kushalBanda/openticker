import json
from typing import Any

from agents.advisors.core.exceptions import InvalidProposalError
from agents.advisors.core.retry import propose_with_fallback
from agents.advisors.pairs_trading.prompt import build_prompt
from agents.advisors.pairs_trading.schema import (
    CandidateStats,
    PairsTradingProposal,
    SelectedPairWeight,
    validate_proposal,
)
from agents.llm import LLMClient


def _parse_proposal(content: str) -> PairsTradingProposal:
    """Parse the Advisor's raw JSON text into a `PairsTradingProposal`.

    Any parse failure (bad JSON, missing/wrong-typed field) is reported as
    `InvalidProposalError`, the same failure channel bounds violations use,
    so `propose_with_fallback` treats a malformed response and an
    out-of-bounds one identically.
    """
    try:
        data: Any = json.loads(content)
    except json.JSONDecodeError as exc:
        raise InvalidProposalError(f"response was not valid JSON: {exc}") from exc

    try:
        selected = tuple(
            SelectedPairWeight(
                symbol_a=str(item["symbol_a"]),
                symbol_b=str(item["symbol_b"]),
                weight=float(item["weight"]),
            )
            for item in data["selected"]
        )
        return PairsTradingProposal(
            entry_z=float(data["entry_z"]),
            formation_months=int(data["formation_months"]),
            trading_months=int(data["trading_months"]),
            buffer=float(data["buffer"]),
            selected=selected,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidProposalError(f"response JSON missing/invalid field: {exc}") from exc


class PairsTradingAdvisor:
    """LLM-driven Advisor for `PairsTradingStrategy`'s reformation cycle.
    """

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def propose(
        self, candidates: list[CandidateStats], prior: PairsTradingProposal
    ) -> PairsTradingProposal:
        candidate_symbols = {(c.symbol_a, c.symbol_b) for c in candidates}

        async def attempt(feedback: str | None) -> PairsTradingProposal:
            messages = build_prompt(candidates, prior, feedback)
            response = await self._llm.acomplete(messages)
            proposal = _parse_proposal(response.content)
            validate_proposal(proposal, candidate_symbols)
            return proposal

        return await propose_with_fallback(attempt, prior)
