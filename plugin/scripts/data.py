"""Shared bar-fetching helpers for plugin scripts.

Both fetch_bars.py and run_backtest.py need the same connect-then-
fetch_historical sequence against whichever provider is connected -
factored out here once both needed it, instead of duplicated per script.
"""

import sys
from datetime import datetime
from pathlib import Path

# Sibling scripts (state.py, adapters.py) are not an installed package,
# so importing them by name requires this directory on sys.path first -
# this must run before the sibling imports below, unlike every other
# import in this file.
sys.path.insert(0, str(Path(__file__).resolve().parent))
import ingest.core.exceptions as ingest_exc
from adapters import ensure_adapters_registered
from ingest.core.engine import DataEngine
from ingest.core.models import Bar
from ingest.core.registry import AdapterFactory
from ingest.storage.duckdb_store import DuckDBStore
from state import load_credentials, load_most_recent


def resolve_provider(explicit_provider: str | None) -> tuple[str, dict[str, object]]:
    """Resolve which provider's stored credentials to use.

    Args:
        explicit_provider: A provider name the caller asked for, or None
            to fall back to whichever provider connected most recently.

    Returns:
        The resolved provider name and its stored credentials.

    Raises:
        SystemExit: No adapter is connected yet, or the requested
            provider has no stored session.
    """
    if explicit_provider:
        creds = load_credentials(explicit_provider)
        if creds is None:
            raise SystemExit(
                f"no stored session for provider {explicit_provider!r} - run "
                "the connect-adapter skill first."
            )
        return explicit_provider, creds
    most_recent = load_most_recent()
    if most_recent is None:
        raise SystemExit("no adapter is connected yet - run the connect-adapter skill first.")
    return most_recent


async def connect_engine(provider: str | None) -> tuple[str, DataEngine]:
    """Resolve the provider, build its adapter, connect once, wrap in a DataEngine.

    Call once per script run, then fetch as many symbols as needed
    through the returned engine.

    Args:
        provider: A provider name to use, or None for the most recently
            connected one.

    Returns:
        The resolved provider name and a connected DataEngine.

    Raises:
        SystemExit: No stored session, or the stored session has expired.
    """
    ensure_adapters_registered()
    resolved_provider, creds = resolve_provider(provider)

    adapter = AdapterFactory.create(resolved_provider, creds)
    try:
        await adapter.connect()
    except ingest_exc.AuthExpiredError:
        raise SystemExit(
            f"the stored {resolved_provider} session has expired - reconnect "
            "via the connect-adapter skill."
        ) from None

    engine = DataEngine(adapters={resolved_provider: adapter}, store=DuckDBStore())
    return resolved_provider, engine


async def fetch_symbol_bars(
    engine: DataEngine,
    resolved_provider: str,
    symbol: str,
    interval: str,
    frm: datetime,
    to: datetime,
) -> list[Bar]:
    """Fetch bars for one symbol through an already-connected engine.

    Args:
        engine: A DataEngine returned by connect_engine.
        resolved_provider: The provider name connect_engine resolved.
        symbol: Tradingsymbol to fetch, e.g. "RELIANCE".
        interval: Canonical bar interval, e.g. "1d".
        frm: Range start (inclusive).
        to: Range end (exclusive).

    Returns:
        Bars sorted ascending by timestamp.

    Raises:
        SystemExit: The session expired mid-fetch, or no bars exist for
            the requested symbol/range.
    """
    try:
        bars = await engine.fetch_historical(symbol, interval, frm, to, provider=resolved_provider)
    except ingest_exc.AuthExpiredError:
        raise SystemExit(
            f"the stored {resolved_provider} session has expired - reconnect "
            "via the connect-adapter skill."
        ) from None
    except ingest_exc.DataUnavailableError as exc:
        raise SystemExit(f"no data for {symbol!r}: {exc}") from None

    if not bars:
        raise SystemExit(
            f"no bars found for {symbol!r} in the requested range - try a "
            "different symbol or a wider range."
        )
    return list(bars)
