class EngineError(Exception):
    """Base for errors an MCP tool raises back to the calling harness."""


class NotConnectedError(EngineError):
    """No adapter session is stored for the requested (or most recent) provider."""


class SessionExpiredError(EngineError):
    """A stored adapter session was rejected by the provider as expired."""


class ProviderRateLimitedError(EngineError):
    """The provider rejected a request for exceeding its rate limit."""


class InvalidSignalParamsError(EngineError):
    """A signal's constructor rejected the params passed to it."""


class InvalidStrategyParamsError(EngineError):
    """A strategy's constructor rejected the params passed to it."""
