import pytest
from agents.advisors.core.exceptions import InvalidProposalError
from agents.advisors.core.retry import propose_with_fallback


async def test_returns_first_attempt_when_valid() -> None:
    async def attempt(feedback: str | None) -> str:
        assert feedback is None
        return "ok"

    result = await propose_with_fallback(attempt, prior="prior")
    assert result == "ok"


async def test_retries_once_with_feedback_then_succeeds() -> None:
    calls: list[str | None] = []

    async def attempt(feedback: str | None) -> str:
        calls.append(feedback)
        if feedback is None:
            raise InvalidProposalError("bad first try")
        return "fixed"

    result = await propose_with_fallback(attempt, prior="prior")

    assert result == "fixed"
    assert calls == [None, "bad first try"]


async def test_falls_back_to_prior_after_max_attempts() -> None:
    async def attempt(feedback: str | None) -> str:
        raise InvalidProposalError("always bad")

    result = await propose_with_fallback(attempt, prior="prior")
    assert result == "prior"


async def test_respects_custom_max_attempts() -> None:
    call_count = 0

    async def attempt(feedback: str | None) -> str:
        nonlocal call_count
        call_count += 1
        raise InvalidProposalError("always bad")

    result = await propose_with_fallback(attempt, prior="prior", max_attempts=1)

    assert result == "prior"
    assert call_count == 1


async def test_propagates_unexpected_exceptions() -> None:
    async def attempt(feedback: str | None) -> str:
        raise RuntimeError("not an InvalidProposalError")

    with pytest.raises(RuntimeError, match="not an InvalidProposalError"):
        await propose_with_fallback(attempt, prior="prior")
