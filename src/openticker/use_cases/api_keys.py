"""Create, list, revoke and check REST API keys (ADR 17 in docs/adr).

A key is 32 random bytes, shown once at creation. Only its SHA-256 is stored:
a key has far too much entropy to guess from its hash, so a slow password
hash would add nothing but latency to every request.
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
    key = KEY_PREFIX + secrets.token_urlsafe(32)
    stored = insert_api_key(name, _hash(key), key[:_SHOWN_PREFIX_LENGTH], FULL_SCOPE, now)
    return stored, key


def authenticate(key: str) -> StoredApiKey | None:
    """The active key this is, or None."""
    return find_active_api_key(_hash(key))


def get_api_keys() -> list[StoredApiKey]:
    return list_api_keys()


def revoke(name: str, now: datetime) -> bool:
    return revoke_api_key(name, now)


def _hash(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()
