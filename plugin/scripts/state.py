"""Local credential store for the Quant Platform plugin.

Home-scoped, single-user, no server involved. Holds each connected
provider's raw credentials exactly as `ingest.core.registry.AdapterFactory
.create(provider, credentials)` needs them - nothing is wrapped in a JWT
or any other token format, because there is no auth boundary to cross:
this file and the process reading it always belong to the same user.

Stdlib only, on purpose - this module has no dependency on the uv
workspace, so it works even before any packages/* package is installed.
"""

import json
import os
import sqlite3
import stat
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATE_DIR = Path.home() / ".quant-plugin"
STATE_DB = STATE_DIR / "state.db"

_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR  # 0600, owner read/write only


def _ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(STATE_DIR, stat.S_IRWXU)  # 0700, owner-only


def _connect() -> sqlite3.Connection:
    _ensure_state_dir()
    is_new = not STATE_DB.exists()
    conn = sqlite3.connect(STATE_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS credentials (
            provider TEXT PRIMARY KEY,
            credentials_json TEXT NOT NULL,
            connected_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    if is_new:
        os.chmod(STATE_DB, _FILE_MODE)
    else:
        # Re-assert on every connect in case something (an editor, a
        # backup tool) loosened it after creation.
        os.chmod(STATE_DB, _FILE_MODE)
    return conn


def save_credentials(provider: str, credentials: Mapping[str, Any]) -> None:
    """Write (or overwrite) one provider's credentials, stamped with now."""
    connected_at = datetime.now(UTC).isoformat()
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO credentials (provider, credentials_json, connected_at)
            VALUES (?, ?, ?)
            ON CONFLICT(provider) DO UPDATE SET
                credentials_json = excluded.credentials_json,
                connected_at = excluded.connected_at
            """,
            (provider, json.dumps(dict(credentials)), connected_at),
        )
        conn.commit()
    finally:
        conn.close()


def load_credentials(provider: str) -> dict[str, Any] | None:
    """Return one provider's stored credentials, or None if never connected."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT credentials_json FROM credentials WHERE provider = ?",
            (provider,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    result: dict[str, Any] = json.loads(row[0])
    return result


def load_most_recent() -> tuple[str, dict[str, Any]] | None:
    """Return (provider, credentials) for whichever provider connected last.

    Used by the research skill (ticket 05) when more than one provider is
    connected, so it doesn't have to guess which one to use.
    """
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT provider, credentials_json FROM credentials
            ORDER BY connected_at DESC LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    provider, credentials_json = row
    return provider, json.loads(credentials_json)


def list_providers() -> list[str]:
    conn = _connect()
    try:
        rows = conn.execute("SELECT provider FROM credentials").fetchall()
    finally:
        conn.close()
    return [r[0] for r in rows]


if __name__ == "__main__":
    # Manual round-trip check, per this ticket's "Verifiable" line - not a
    # pytest suite (this plugin is exempted from the workspace's strict
    # lint/type bar), just proof the store actually works end to end.
    save_credentials("_selftest", {"api_key": "fake", "access_token": "fake"})
    assert load_credentials("_selftest") == {"api_key": "fake", "access_token": "fake"}
    assert load_most_recent() is not None
    assert "_selftest" in list_providers()
    mode = oct(STATE_DB.stat().st_mode & 0o777)
    assert mode == "0o600", f"expected 0600 permissions, got {mode}"
    print(f"OK - state store round-trips correctly at {STATE_DB} (mode {mode})")
