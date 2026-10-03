"""Browser sign-in for the web app (ADR 31 in docs/adr).

`openticker-serve` prints a one-time link; opening it swaps the link for a
session cookie. A session lasts 30 days from its last use. A visit starts
when the session is used again after 10 idle minutes; the Today view tells
the user what happened since the previous one.
"""

from datetime import datetime

from openticker.core.web import (
    NEW_VISIT_AFTER,
    SESSION_LIFETIME,
    SESSION_TOUCH_EVERY,
    SIGN_IN_LINK_LIFETIME,
    new_secret,
    secret_hash,
)
from openticker.storage.sqlite.web_repo import (
    WebSession,
    find_session,
    insert_link,
    insert_session,
    redeem_link,
    revoke_all_sessions,
    revoke_session,
    touch_session,
)


def create_sign_in_link(base_url: str, now: datetime) -> str:
    """The full link, shown once: only its hash is kept."""
    token = new_secret()
    insert_link(secret_hash(token), now, now + SIGN_IN_LINK_LIFETIME)
    return f"{base_url}/login?token={token}"


def redeem_sign_in_link(token: str, user_agent: str | None, now: datetime) -> str | None:
    """A new session's secret, for the cookie; None when the link is unknown,
    used or expired."""
    if not redeem_link(secret_hash(token), now):
        return None
    secret = new_secret()
    insert_session(secret_hash(secret), now, now + SESSION_LIFETIME, user_agent)
    return secret


def session_of(secret: str, now: datetime) -> WebSession | None:
    """The live session this secret opens, or None. A use pushes its expiry
    30 days on, written at most once a minute."""
    session = find_session(secret_hash(secret))
    if session is None or session.revoked_at is not None or session.expires_at <= now:
        return None
    idle = now - session.last_seen_at
    if idle < SESSION_TOUCH_EVERY:
        return session
    new_visit = idle >= NEW_VISIT_AFTER
    touch_session(session.id_hash, now, now + SESSION_LIFETIME, new_visit)
    return find_session(session.id_hash)


def sign_out(secret: str, now: datetime) -> None:
    revoke_session(secret_hash(secret), now)


def sign_out_everywhere(now: datetime) -> int:
    """How many sessions were ended."""
    return revoke_all_sessions(now)
