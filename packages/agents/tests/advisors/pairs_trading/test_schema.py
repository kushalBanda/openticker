import pytest
from agents.advisors.core.exceptions import InvalidProposalError
from agents.advisors.pairs_trading.schema import (
    PairsTradingProposal,
    SelectedPairWeight,
    validate_proposal,
)

_CANDIDATES = {("A", "B"), ("C", "D")}


def _proposal(**overrides: object) -> PairsTradingProposal:
    defaults: dict[str, object] = {
        "entry_z": 2.0,
        "formation_months": 6,
        "trading_months": 3,
        "buffer": 0.1,
        "selected": (SelectedPairWeight("A", "B", 0.9),),
    }
    defaults.update(overrides)
    return PairsTradingProposal(**defaults)  # type: ignore[arg-type]


def test_valid_proposal_passes() -> None:
    validate_proposal(_proposal(), _CANDIDATES)


@pytest.mark.parametrize("entry_z", [1.4, 3.6])
def test_entry_z_out_of_bounds_rejected(entry_z: float) -> None:
    with pytest.raises(InvalidProposalError, match="entry_z"):
        validate_proposal(_proposal(entry_z=entry_z), _CANDIDATES)


@pytest.mark.parametrize("buffer", [0.04, 0.26])
def test_buffer_out_of_bounds_rejected(buffer: float) -> None:
    with pytest.raises(InvalidProposalError, match="buffer"):
        validate_proposal(_proposal(buffer=buffer), _CANDIDATES)


def test_empty_selection_rejected() -> None:
    with pytest.raises(InvalidProposalError, match="empty"):
        validate_proposal(_proposal(selected=()), _CANDIDATES)


def test_pair_outside_candidate_window_rejected() -> None:
    proposal = _proposal(selected=(SelectedPairWeight("X", "Y", 0.9),))
    with pytest.raises(InvalidProposalError, match="not in the candidate window"):
        validate_proposal(proposal, _CANDIDATES)


def test_duplicate_pair_rejected() -> None:
    proposal = _proposal(
        selected=(SelectedPairWeight("A", "B", 0.5), SelectedPairWeight("A", "B", 0.4))
    )
    with pytest.raises(InvalidProposalError, match="selected more than once"):
        validate_proposal(proposal, _CANDIDATES)


def test_non_positive_weight_rejected() -> None:
    proposal = _proposal(selected=(SelectedPairWeight("A", "B", 0.0),))
    with pytest.raises(InvalidProposalError, match="must be positive"):
        validate_proposal(proposal, _CANDIDATES)


def test_weights_not_reconciling_to_buffer_rejected() -> None:
    proposal = _proposal(buffer=0.1, selected=(SelectedPairWeight("A", "B", 0.5),))
    with pytest.raises(InvalidProposalError, match="expected"):
        validate_proposal(proposal, _CANDIDATES)


def test_weights_summing_correctly_across_multiple_pairs_passes() -> None:
    proposal = _proposal(
        buffer=0.1,
        selected=(
            SelectedPairWeight("A", "B", 0.6),
            SelectedPairWeight("C", "D", 0.3),
        ),
    )
    validate_proposal(proposal, _CANDIDATES)
