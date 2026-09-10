"""Shared bar-fetching helpers for plugin scripts.

Both fetch_bars.py and run_backtest.py need the same connect-then-
fetch_historical sequence against whichever provider is connected -
factored out here once both needed it, instead of duplicated per script.
"""

import sys
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from adapters import ensure_adapters_registered
from ingest.core.models import Bar
from state import load_credentials, load_most_recent


def resolve_provider(explicit_provider: str | None) -> tuple[str, dict[str, object]]:
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


async def connect_engine(provider: str | None) -> tuple[str, Any]:
    """Resolves the provider, builds its adapter, connects once, and wraps
    it in a DataEngine. Call once per script run, then fetch as many
    symbols as needed through the returned engine.
    """
    import ingest.core.exceptions as ingest_exc
    from ingest.core.engine import DataEngine
    from ingest.core.registry import AdapterFactory
    from ingest.storage.duckdb_store import DuckDBStore

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
    engine: Any,
    resolved_provider: str,
    symbol: str,
    interval: str,
    frm: datetime,
    to: datetime,
) -> list[Bar]:
    """Fetches bars for one symbol through an already-connected engine.
    Raises SystemExit with a plain message on an expired session or no
    data, same wording fetch_bars.py has always used.
    """
    import ingest.core.exceptions as ingest_exc

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
