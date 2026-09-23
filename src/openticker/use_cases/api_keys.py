"""Create, list, revoke and check REST API keys (ADR 17 in docs/adr).

A key is 32 random bytes, shown once at creation. Only its SHA-256 is stored:
a key has far too much entropy to guess from its hash, so a slow password
hash would add nothing but latency to every request.

Each run of a hosted script gets its own key, scoped to trading routes and
revoked when the run ends (ADR 25 in docs/adr).
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
_SCRIPT_KEY_NAME_PREFIX = "script-"  # then the run's id
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
    if name.startswith(_SCRIPT_KEY_NAME_PREFIX):
        raise InvalidApiKeyNameError(
            f"key names starting {_SCRIPT_KEY_NAME_PREFIX!r} are kept for hosted scripts"
        )
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


def authenticate(key: str) -> StoredApiKey | None:
    """The active key this is, or None."""
    return find_active_api_key(_hash(key))


def get_api_keys() -> list[StoredApiKey]:
    return list_api_keys()


def revoke(name: str, now: datetime) -> bool:
    return revoke_api_key(name, now)


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()
