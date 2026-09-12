"""Errors a skill script's mechanics layer can raise.

Ported from ingest.core.exceptions + engine.core.exceptions, merged into
one flat module since there is no longer an ingest/engine package split.
"""


class AdapterError(Exception):
    """Base for any Kite mechanics failure."""


class AuthExpiredError(AdapterError):
    """The stored session was rejected by the provider as expired."""


class RateLimitError(AdapterError):
    """The provider rejected a request for exceeding its rate limit."""


class DataUnavailableError(AdapterError):
    """No data exists for the requested symbol/range, or a lookup missed."""


class NotConnectedError(AdapterError):
    """No stored session exists for the requested (or most recent) provider."""
