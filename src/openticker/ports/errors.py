"""Errors every broker adapter raises through, so inbound adapters can tell an
expected, caller-fixable failure from a crash without knowing any broker."""


class BrokerError(Exception):
    """A broker call failed in a way the caller can act on; the message says how."""


class BrokerSessionError(BrokerError):
    """No session, or the broker rejected it (expired, revoked) — reconnect the broker."""
