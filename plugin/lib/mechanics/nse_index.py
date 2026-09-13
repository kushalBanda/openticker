"""Flat NSE index-constituent fetch plus a local cache. Used only when a
scan-market run names a universe scope (Nifty 50/500, midcap, smallcap).
Not on the critical path for a scopeless or single-stock/sector scan.
"""

import csv
import io
import os
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import duckdb
import httpx

from lib.mechanics.exceptions import DataUnavailableError

INDEX_NIFTY_50: Final = "nifty_50"
INDEX_NIFTY_500: Final = "nifty_500"
INDEX_NIFTY_MIDCAP_150: Final = "nifty_midcap_150"
INDEX_NIFTY_SMALLCAP_250: Final = "nifty_smallcap_250"

_INDEX_CSV_URLS: Final[dict[str, str]] = {
    INDEX_NIFTY_50: "https://archives.nseindia.com/content/indices/ind_nifty50list.csv",
    INDEX_NIFTY_500: "https://archives.nseindia.com/content/indices/ind_nifty500list.csv",
    INDEX_NIFTY_MIDCAP_150: "https://archives.nseindia.com/content/indices/ind_niftymidcap150list.csv",
    INDEX_NIFTY_SMALLCAP_250: "https://archives.nseindia.com/content/indices/ind_niftysmallcap250list.csv",
}

_USER_AGENT: Final = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

DEFAULT_CACHE_DB_PATH: Final = Path.home() / ".quant-plugin" / "nse_index_cache.duckdb"
TABLE_INDEX_CONSTITUENTS: Final = "index_constituents"
CACHE_MAX_AGE: Final = timedelta(days=1)

_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR  # 0600, owner read/write only


class NseIndexCache:
    def __init__(self, db_path: Path = DEFAULT_CACHE_DB_PATH) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(str(db_path))
        os.chmod(db_path, _FILE_MODE)
        self.ensure_schema()

    def ensure_schema(self) -> None:
        self._conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE_INDEX_CONSTITUENTS} (
                index_name TEXT NOT NULL,
                symbol TEXT NOT NULL,
                fetched_at TIMESTAMPTZ NOT NULL,
                PRIMARY KEY (index_name, symbol)
            )
        """)

    def read_cached(self, index_name: str) -> tuple[list[str], datetime] | None:
        rows = self._conn.execute(
            f"SELECT symbol, fetched_at FROM {TABLE_INDEX_CONSTITUENTS} WHERE index_name = ?",
            [index_name],
        ).fetchall()
        if not rows:
            return None
        return [r[0] for r in rows], rows[0][1]

    def write_cache(self, index_name: str, symbols: list[str], fetched_at: datetime) -> None:
        self._conn.execute(f"DELETE FROM {TABLE_INDEX_CONSTITUENTS} WHERE index_name = ?", [index_name])
        self._conn.executemany(
            f"INSERT INTO {TABLE_INDEX_CONSTITUENTS} (index_name, symbol, fetched_at) VALUES (?, ?, ?)",
            [(index_name, symbol, fetched_at) for symbol in symbols],
        )


def _parse_constituent_csv(csv_text: str) -> list[str]:
    reader = csv.DictReader(io.StringIO(csv_text))
    symbols = [row["Symbol"].strip() for row in reader if row.get("Symbol")]
    if not symbols:
        raise DataUnavailableError("NSE index constituent CSV had no Symbol column data")
    return symbols


async def fetch_index_constituents(index_name: str, cache: NseIndexCache | None = None) -> list[str]:
    if index_name not in _INDEX_CSV_URLS:
        raise ValueError(f"unknown index {index_name!r}, expected one of {sorted(_INDEX_CSV_URLS)}")
    store = cache if cache is not None else NseIndexCache()
    cached = store.read_cached(index_name)
    now = datetime.now(UTC)
    if cached is not None:
        symbols, fetched_at = cached
        if now - fetched_at < CACHE_MAX_AGE:
            return symbols
    async with httpx.AsyncClient(headers={"User-Agent": _USER_AGENT}, timeout=15.0) as client:
        response = await client.get(_INDEX_CSV_URLS[index_name])
        response.raise_for_status()
    symbols = _parse_constituent_csv(response.text)
    store.write_cache(index_name, symbols, now)
    return symbols
