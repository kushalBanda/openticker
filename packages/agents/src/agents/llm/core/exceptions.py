class LLMError(Exception):
    """Base exception for the llm package."""


class LLMCallFailedError(LLMError):
    """Raised when the underlying litellm call fails.

    Wraps litellm's provider-specific exception hierarchy (auth, rate
    limit, timeout, bad request, provider outage, ...) behind one typed
    error so callers don't need to know which provider they're talking to.
    """
