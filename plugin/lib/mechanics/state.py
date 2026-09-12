"""Local credential store for the Quant Platform plugin.

Home-scoped, single-user, no server involved. Ported from
engine.core.state unchanged - it was already a flat module with no
ingest/quant/strategy dependency.

DuckDB-backed, its own file (credentials.duckdb), separate from the bars
store's quant.duckdb even though both live under ~/.quant-plugin/. Kept
as two files on purpose: DuckDB holds one exclusive cross-process write
lock per file for as long as a connection is open, and a fetch-bars call
can hold quant.duckdb open for the length of a whole fetch loop. Sharing
one file would let a slow fetch in one skill block a connect-adapter call
running at the same time.
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
    """Return (provider, credentials) for whichever provider connected last."""
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
