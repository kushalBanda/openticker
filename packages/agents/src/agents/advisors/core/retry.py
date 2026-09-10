import logging
from collections.abc import Awaitable, Callable

from agents.advisors.core.exceptions import InvalidProposalError

logger = logging.getLogger(__name__)


async def propose_with_fallback[ProposalT](
    attempt: Callable[[str | None], Awaitable[ProposalT]],
    prior: ProposalT,
    max_attempts: int = 2,
) -> ProposalT:
    """Call `attempt` up to `max_attempts` times.

    `attempt(feedback)` is called with `feedback=None` on the first try; if
    it raises `InvalidProposalError`, the error message is fed back as
    `feedback` on the next try. If every attempt still fails, `prior` is
    returned unchanged and the failure is logged — a backtest never halts
    on one bad Advisor call. Shared across every strategy's advisor, not
    duplicated per advisor.
    """
    feedback: str | None = None
    for attempt_number in range(1, max_attempts + 1):
        try:
            return await attempt(feedback)
        except InvalidProposalError as exc:
            feedback = str(exc)
            logger.warning(
                "advisor proposal attempt %d/%d invalid: %s",
                attempt_number,
                max_attempts,
                exc,
            )
    logger.warning(
        "advisor proposal failed after %d attempts, falling back to prior params",
        max_attempts,
    )
    return prior
