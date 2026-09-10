class AdvisorError(Exception):
    """Base exception for the advisors package."""


class InvalidProposalError(AdvisorError):
    """Raised when an Advisor's proposal is malformed, out of bounds, or
    breaks capital conservation. Caught by `core.retry.propose_with_fallback`
    and treated as one failed attempt, never lets a bad LLM response through
    unvalidated.
    """
