"""Create, list, revoke and check REST API keys (ADR 17 in docs/adr).

A key is 32 random bytes, shown once at creation. Only its SHA-256 is stored:
a key has far too much entropy to guess from its hash, so a slow password
hash would add nothing but latency to every request.

Each run of a hosted script gets its own key, scoped to trading routes and
revoked when the run ends (ADR 25 in docs/adr). Each agent job gets one too,
scoped to what its kind may read: a review, its own strategy (ADR 29).
"""

import hashlib
import re
import secrets
from datetime import datetime

from openticker.storage.sqlite.api_keys_repo import (
    StoredApiKey,
    find_active_api_key,
    insert_api_key,
    list_api_keys,
    revoke_api_key,
)

KEY_PREFIX = "otk_"
FULL_SCOPE = "full"
SCRIPT_SCOPE_PREFIX = "script:"  # then the script's id
REVIEW_SCOPE_PREFIX = "review:"  # then the strategy's id
_SCRIPT_KEY_NAME_PREFIX = "script-"  # then the run's id
_AGENT_KEY_NAME_PREFIX = "agent-"  # then the job's id
_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")
_SHOWN_PREFIX_LENGTH = len(KEY_PREFIX) + 6


class InvalidApiKeyNameError(Exception):
    pass


def create_api_key(name: str, now: datetime) -> tuple[StoredApiKey, str]:
    """The stored key and the key itself, which is never retrievable again."""
    if not _NAME.fullmatch(name):
        raise InvalidApiKeyNameError(
            f"key name {name!r} must be 1-40 lowercase letters, digits, '-' or '_'"
        )
    for reserved, owner in (
        (_SCRIPT_KEY_NAME_PREFIX, "hosted scripts"),
        (_AGENT_KEY_NAME_PREFIX, "agent jobs"),
    ):
        if name.startswith(reserved):
            raise InvalidApiKeyNameError(f"key names starting {reserved!r} are kept for {owner}")
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    stored = insert_api_key(name, _hash(key), key[:_SHOWN_PREFIX_LENGTH], FULL_SCOPE, now)
    return stored, key


def create_script_key(script_id: str, run_id: str, now: datetime) -> str:
    """A key for one run of a script, never stored except as its hash."""
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    insert_api_key(
        script_key_name(run_id),
        _hash(key),
        key[:_SHOWN_PREFIX_LENGTH],
        SCRIPT_SCOPE_PREFIX + script_id,
        now,
    )
    return key


def script_key_name(run_id: str) -> str:
    return _SCRIPT_KEY_NAME_PREFIX + run_id


def revoke_script_keys(keep_runs: set[str], now: datetime) -> int:
    """Revokes every script key but those of `keep_runs`; how many were."""
    keep = {script_key_name(run_id) for run_id in keep_runs}
    revoked = 0
    for stored in list_api_keys():
        if (
            stored.revoked_at is None
            and stored.scope.startswith(SCRIPT_SCOPE_PREFIX)
            and stored.name not in keep
        ):
            revoked += revoke_api_key(stored.name, now)
    return revoked


def create_review_key(strategy_id: str, job_id: str, now: datetime) -> str:
    """A key for one review job: reads that strategy and market data only."""
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    insert_api_key(
        agent_key_name(job_id),
        _hash(key),
        key[:_SHOWN_PREFIX_LENGTH],
        REVIEW_SCOPE_PREFIX + strategy_id,
        now,
    )
    return key


def agent_key_name(job_id: str) -> str:
    return _AGENT_KEY_NAME_PREFIX + job_id


def revoke_agent_keys(now: datetime) -> int:
    """Revokes every agent job's key; how many were."""
    revoked = 0
    for stored in list_api_keys():
        if stored.revoked_at is None and stored.name.startswith(_AGENT_KEY_NAME_PREFIX):
            revoked += revoke_api_key(stored.name, now)
    return revoked


def authenticate(key: str) -> StoredApiKey | None:
    """The active key this is, or None."""
    return find_active_api_key(_hash(key))


def get_api_keys() -> list[StoredApiKey]:
    return list_api_keys()


def revoke(name: str, now: datetime) -> bool:
    return revoke_api_key(name, now)


class UnknownApiKeyError(LookupError):
    pass


class ManagedApiKeyError(Exception):
    pass


def revoke_user_key(name: str, now: datetime) -> None:
    """Revokes a key the user made. A script run's or an agent job's key is
    OpenTicker's to revoke, when the run or job ends."""
    stored = next((k for k in list_api_keys() if k.name == name and k.revoked_at is None), None)
    if stored is None:
        raise UnknownApiKeyError(f"no active API key named {name!r}")
    if stored.scope != FULL_SCOPE:
        raise ManagedApiKeyError(
            f"{name!r} belongs to a running script or agent job and is revoked when it ends; "
            "stop the script or the job instead"
        )
    revoke_api_key(name, now)


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()
