"""A proposal: one change to one strategy, raised by an agent and decided by
the user. Deciding changes nothing by itself: accepting gives the request
to paste into the user's own agent, which changes the strategy between runs
(ADR 21). A rejected proposal keeps its reason, which agents read before
proposing something similar.

    OPEN ──accept──▶ ACCEPTED (final)
      │ ▲
 later│ │accept / reject / later
      ▼ │
    LATER ──reject (with a reason)──▶ REJECTED (final)
"""

from dataclasses import dataclass
from enum import StrEnum

from openticker.core.brain.notes import MAX_BODY, MAX_LINE, MAX_TITLE, BrainNoteError


class ProposalState(StrEnum):
    OPEN = "open"
    LATER = "later"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class Decision(StrEnum):
    ACCEPT = "accept"
    REJECT = "reject"
    LATER = "later"


MAX_BASED_ON = 10

_AFTER: dict[Decision, ProposalState] = {
    Decision.ACCEPT: ProposalState.ACCEPTED,
    Decision.REJECT: ProposalState.REJECTED,
    Decision.LATER: ProposalState.LATER,
}


@dataclass(frozen=True)
class Proposal:
    strategy_id: str
    change: str  # the one change, in one line; also its title
    why: str  # markdown
    wrong_if: str  # what could make it wrong
    based_on: tuple[str, ...]  # lesson ids


def validate_proposal(proposal: Proposal) -> Proposal:
    """The proposal with its text trimmed and its lessons once each."""
    strategy_id = proposal.strategy_id.strip()
    change, why, wrong_if = proposal.change.strip(), proposal.why.strip(), proposal.wrong_if.strip()
    if not strategy_id:
        raise BrainNoteError("a proposal is about one strategy: give its strategy_id")
    if not change:
        raise BrainNoteError("a proposal needs its change: the one thing to change, in one line")
    if not why:
        raise BrainNoteError("a proposal needs its why: the evidence for the change")
    if not wrong_if:
        raise BrainNoteError("say what could make the proposal wrong: the user weighs it")
    _within(change, MAX_TITLE, "the change")
    _within(why, MAX_BODY, "the why")
    _within(wrong_if, MAX_LINE, "what could make it wrong")
    based_on = tuple(dict.fromkeys(b.strip() for b in proposal.based_on if b.strip()))
    if len(based_on) > MAX_BASED_ON:
        raise BrainNoteError(f"a proposal rests on at most {MAX_BASED_ON} lessons")
    return Proposal(strategy_id, change, why, wrong_if, based_on)


def decide(state: ProposalState, decision: Decision, reason: str | None) -> ProposalState:
    """The state after `decision`. Open and later proposals take any decision;
    accepted and rejected ones are final. Rejecting needs a reason."""
    if state in (ProposalState.ACCEPTED, ProposalState.REJECTED):
        raise BrainNoteError(f"the proposal was {state.value} already; that's final")
    if decision is Decision.REJECT and not (reason or "").strip():
        raise BrainNoteError("say why it's rejected: agents read the reason before proposing again")
    if reason is not None:
        _within(reason.strip(), MAX_LINE, "the reason")
    return _AFTER[decision]


def request_text(strategy_id: str, strategy_name: str | None, change: str, proposal_id: str) -> str:
    """What the user pastes into their agent once they accept."""
    named = f"{strategy_name} ({strategy_id})" if strategy_name else strategy_id
    return (
        f"Change strategy {named}: {change.rstrip('.')}. Accepted proposal {proposal_id}; "
        "read it with get_brain_note first, and change the strategy only while no run is open."
    )


def _within(text: str, most: int, what: str) -> None:
    if len(text) > most:
        raise BrainNoteError(f"{what} is {len(text):,} characters; at most {most:,}")
