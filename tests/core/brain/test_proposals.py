import pytest

from openticker.core.brain.notes import BrainNoteError
from openticker.core.brain.proposals import (
    Decision,
    Proposal,
    ProposalState,
    decide,
    request_text,
    validate_proposal,
)


def test_reject_needs_reason() -> None:
    with pytest.raises(BrainNoteError, match="say why"):
        decide(ProposalState.OPEN, Decision.REJECT, " ")
    assert decide(ProposalState.OPEN, Decision.REJECT, "margin") is ProposalState.REJECTED


@pytest.mark.parametrize("final", [ProposalState.ACCEPTED, ProposalState.REJECTED])
def test_accepted_and_rejected_are_final(final: ProposalState) -> None:
    for decision in Decision:
        with pytest.raises(BrainNoteError, match="final"):
            decide(final, decision, "x")


def test_later_can_be_decided_again() -> None:
    assert decide(ProposalState.OPEN, Decision.LATER, None) is ProposalState.LATER
    assert decide(ProposalState.LATER, Decision.LATER, None) is ProposalState.LATER
    assert decide(ProposalState.LATER, Decision.ACCEPT, None) is ProposalState.ACCEPTED


def test_request_text_names_strategy_and_proposal() -> None:
    text = request_text("stg_1", "NIFTY short straddle", "Exit at 11:00 on expiry.", "prp_1")
    assert text.startswith("Change strategy NIFTY short straddle (stg_1): Exit at 11:00 on expiry.")
    assert "prp_1" in text and "no run is open" in text
    assert request_text("stg_1", None, "x", "prp_1").startswith("Change strategy stg_1: x.")


def test_proposal_needs_its_parts_and_names_lessons_once() -> None:
    proposal = validate_proposal(Proposal(" stg ", " c ", " w ", " r ", ("les_1", " les_1", "")))
    assert proposal == Proposal("stg", "c", "w", "r", ("les_1",))
    for broken, refusal in [
        (Proposal("", "c", "w", "r", ()), "strategy_id"),
        (Proposal("s", "", "w", "r", ()), "needs its change"),
        (Proposal("s", "c", "", "r", ()), "needs its why"),
        (Proposal("s", "c", "w", "", ()), "could make the proposal wrong"),
        (Proposal("s", "c" * 121, "w", "r", ()), "at most 120"),
        (Proposal("s", "c", "w", "r", tuple(f"les_{n}" for n in range(11))), "at most 10"),
    ]:
        with pytest.raises(BrainNoteError, match=refusal):
            validate_proposal(broken)
