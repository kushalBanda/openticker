import json
from typing import Any

from agents.advisors.pairs_trading.constants import (
    BUFFER_MAX,
    BUFFER_MIN,
    ENTRY_Z_MAX,
    ENTRY_Z_MIN,
    FORMATION_MONTHS_MAX,
    FORMATION_MONTHS_MIN,
    TRADING_MONTHS_MAX,
    TRADING_MONTHS_MIN,
)
from agents.advisors.pairs_trading.schema import CandidateStats, PairsTradingProposal
from agents.llm import Message

_SYSTEM_PROMPT = f"""You are the parameter-tuning advisor for a pairs-trading strategy \
(Gatev, Goetzmann & Rouwenhorst). Each reformation cycle you are shown a candidate window \
of pairs ranked by sum-of-squared-deviation (SSD, tighter co-movement first) and the prior \
cycle's params. You decide which pairs to trade this cycle, how to weight capital across \
them, how much capital to hold back as a buffer, and the entry z-score / lookback windows.

Reply with ONLY a single JSON object, no prose, no markdown fences, exactly this shape:
{{
  "entry_z": <float in [{ENTRY_Z_MIN}, {ENTRY_Z_MAX}]>,
  "formation_months": <int in [{FORMATION_MONTHS_MIN}, {FORMATION_MONTHS_MAX}]>,
  "trading_months": <int in [{TRADING_MONTHS_MIN}, {TRADING_MONTHS_MAX}]>,
  "buffer": <float in [{BUFFER_MIN}, {BUFFER_MAX}]>,
  "selected": [
    {{"symbol_a": "...", "symbol_b": "...", "weight": <float>}}
  ]
}}

Rules:
- Only select pairs that appear in the candidate window below; never invent a pair.
- Never select the same pair twice.
- "weight" values across every selected pair must sum to exactly (1 - buffer).
- A pair with no "win_rate"/"realized_pnl"/"trade_count" field has never been traded before \
— treat that as no information, not as a bad track record.
"""


def _format_candidate(candidate: CandidateStats) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "symbol_a": candidate.symbol_a,
        "symbol_b": candidate.symbol_b,
        "ssd": candidate.ssd,
        "spread_mean": candidate.spread_mean,
        "spread_std": candidate.spread_std,
        "realized_vol": candidate.realized_vol,
        "correlation": candidate.correlation,
    }
    if candidate.win_rate is not None:
        payload["win_rate"] = candidate.win_rate
    if candidate.realized_pnl is not None:
        payload["realized_pnl"] = candidate.realized_pnl
    if candidate.trade_count is not None:
        payload["trade_count"] = candidate.trade_count
    return payload


def _format_prior(prior: PairsTradingProposal) -> dict[str, Any]:
    return {
        "entry_z": prior.entry_z,
        "formation_months": prior.formation_months,
        "trading_months": prior.trading_months,
        "buffer": prior.buffer,
        "selected": [
            {"symbol_a": s.symbol_a, "symbol_b": s.symbol_b, "weight": s.weight}
            for s in prior.selected
        ],
    }


def build_prompt(
    candidates: list[CandidateStats],
    prior: PairsTradingProposal,
    feedback: str | None = None,
) -> list[Message]:
    """Build the chat messages for one Advisor call.

    `feedback` is the prior attempt's `InvalidProposalError` message, set
    only on a retry (see `core.retry.propose_with_fallback`).
    """
    user_payload = {
        "candidate_window": [_format_candidate(candidate) for candidate in candidates],
        "prior_cycle_params": _format_prior(prior),
    }
    user_content = json.dumps(user_payload, indent=2)
    if feedback:
        user_content += (
            f"\n\nYour previous response was invalid: {feedback}\n"
            "Return a corrected JSON object only."
        )

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
