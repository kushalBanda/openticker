"""Errors every broker adapter raises through, so inbound adapters can tell an
expected, caller-fixable failure from a crash without knowing any broker."""


class BrokerError(Exception):
    """A broker call failed in a way the caller can act on; the message says how."""


class BrokerRateLimitError(BrokerError):
    """The broker refused the call for asking too often; wait before the next."""


class BrokerSessionError(BrokerError):
    """No session, or the broker rejected it (expired, revoked) — reconnect the broker."""


class BrokerNotConnectedError(BrokerSessionError):
    """No session is stored: the user never logged in, or disconnected."""
