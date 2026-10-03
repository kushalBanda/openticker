"""The web app's sign-in rules (ADR 31 in docs/adr): how long a sign-in link
and a browser session last, the secrets behind them, and which Host and
Origin headers a browser request may carry.

A browser session is a cookie, so any page the browser visits could send
it. Two checks keep other sites out: the Host must be a loopback name on
this server's port (a DNS-rebinding page arrives under its own name), and a
request that changes something must come from this server's own origin.
"""

import hashlib
import ipaddress
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

SIGN_IN_LINK_LIFETIME = timedelta(minutes=10)
SESSION_LIFETIME = timedelta(days=30)  # sliding: renewed while the session is used
SESSION_TOUCH_EVERY = timedelta(minutes=1)
NEW_VISIT_AFTER = timedelta(minutes=10)
COOKIE_NAME = "ot_session"


def new_secret() -> str:
    """32 random bytes, URL-safe: a sign-in link's token or a session's cookie."""
    return secrets.token_urlsafe(32)


def secret_hash(secret: str) -> str:
    """What is stored instead of the secret. SHA-256, not a slow password
    hash: the secret has far too much entropy to guess (as with API keys)."""
    return hashlib.sha256(secret.encode()).hexdigest()


def host_allowed(host_header: str | None, port: int) -> bool:
    """A loopback name on this server's port. A Host without a port means 80."""
    if not host_header:
        return False
    parts = urlsplit(f"//{host_header}")
    try:
        host_port = parts.port or 80
    except ValueError:
        return False
    return _is_loopback(parts.hostname) and host_port == port


def origin_allowed(origin: str | None, own: str, dev_origin: str | None) -> bool:
    """The server's own origin, under any loopback name, or the dev server's
    origin when one is set. A missing or "null" origin never is."""
    if not origin or origin == "null":
        return False
    allowed = [own] + ([dev_origin] if dev_origin else [])
    return _origin_key(origin) in {_origin_key(each) for each in allowed}


def _origin_key(origin: str) -> tuple[str, str | None, int | None] | None:
    parts = urlsplit(origin)
    try:
        port = parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError:
        return None
    host = "loopback" if _is_loopback(parts.hostname) else parts.hostname
    return (parts.scheme, host, port)


def _is_loopback(host: str | None) -> bool:
    if host is None:
        return False
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
