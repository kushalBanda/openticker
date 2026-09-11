"""Local credential store for the Quant Platform plugin.

Home-scoped, single-user, no server involved. Holds each connected
provider's raw credentials exactly as `ingest.core.registry.AdapterFactory
.create(provider, credentials)` needs them - nothing is wrapped in a JWT
or any other token format, because there is no auth boundary to cross:
this file and the process reading it always belong to the same user.

DuckDB-backed, its own file (credentials.duckdb) - a separate file from
ingest's DEFAULT_DB_PATH (bars/ticks/ledger/equity, quant.duckdb) even
though both now live in the same ~/.quant-plugin/ directory and the same
engine. Kept as two files on purpose: DuckDB holds one exclusive
cross-process write lock per file for as long as a connection is open,
and a fetch-bars/run-backtest call can hold quant.duckdb open for the
length of a whole fetch loop. Sharing one file would let a slow fetch in
one session block a connect-adapter call in another. See
docs/HLD/Parent-HLD.md's plugin storage note for the full rationale.
"""

import json
import os
import stat
from collections.abc import Mapping
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

STATE_DIR = Path.home() / ".quant-plugin"
CREDENTIALS_DB = STATE_DIR / "credentials.duckdb"

_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR  # 0600, owner read/write only


def _ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(STATE_DIR, stat.S_IRWXU)  # 0700, owner-only


def _connect() -> duckdb.DuckDBPyConnection:
    """Open (creating if needed) the credentials database with 0600 permissions."""
    _ensure_state_dir()
    conn = duckdb.connect(str(CREDENTIALS_DB))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS credentials (
            provider VARCHAR PRIMARY KEY,
            credentials_json VARCHAR NOT NULL,
            connected_at VARCHAR NOT NULL
        )
        """
    )
    # Re-assert on every connect (not just on creation) in case something
    # (an editor, a backup tool) loosened it after creation.
    os.chmod(CREDENTIALS_DB, _FILE_MODE)
    return conn


def save_credentials(provider: str, credentials: Mapping[str, Any]) -> None:
    """Write (or overwrite) one provider's credentials, stamped with now."""
    connected_at = datetime.now(UTC).isoformat()
    with closing(_connect()) as conn:
        conn.execute(
            """
            INSERT INTO credentials (provider, credentials_json, connected_at)
            VALUES (?, ?, ?)
            ON CONFLICT(provider) DO UPDATE SET
                credentials_json = excluded.credentials_json,
                connected_at = excluded.connected_at
            """,
            [provider, json.dumps(dict(credentials)), connected_at],
        )


def load_credentials(provider: str) -> dict[str, Any] | None:
    """Return one provider's stored credentials, or None if never connected."""
    with closing(_connect()) as conn:
        row = conn.execute(
            "SELECT credentials_json FROM credentials WHERE provider = ?",
            [provider],
        ).fetchone()
    if row is None:
        return None
    result: dict[str, Any] = json.loads(row[0])
    return result


def load_most_recent() -> tuple[str, dict[str, Any]] | None:
    """Return (provider, credentials) for whichever provider connected last.

    Used by the research and run-backtest skills when more than one
    provider is connected, so they don't have to guess which one to use.
    """
    with closing(_connect()) as conn:
        row = conn.execute(
            """
            SELECT provider, credentials_json FROM credentials
            ORDER BY connected_at DESC LIMIT 1
            """
        ).fetchone()
    if row is None:
        return None
    provider, credentials_json = row
    return provider, json.loads(credentials_json)


def list_providers() -> list[str]:
    """Return every provider name with a stored session, in no particular order."""
    with closing(_connect()) as conn:
        rows = conn.execute("SELECT provider FROM credentials").fetchall()
    return [r[0] for r in rows]


if __name__ == "__main__":
    # Manual round-trip check, per this ticket's "Verifiable" line - not a
    # pytest suite (this plugin is exempted from the workspace's strict
    # lint/type bar), just proof the store actually works end to end.
    save_credentials("_selftest", {"api_key": "fake", "access_token": "fake"})
    assert load_credentials("_selftest") == {"api_key": "fake", "access_token": "fake"}
    assert load_most_recent() is not None
    assert "_selftest" in list_providers()
    mode = oct(CREDENTIALS_DB.stat().st_mode & 0o777)
    assert mode == "0o600", f"expected 0600 permissions, got {mode}"
    print(f"OK - state store round-trips correctly at {CREDENTIALS_DB} (mode {mode})")
