"""Shared bar-fetching helpers for engine tools.

Ported from plugin/scripts/data.py, adapted to raise typed exceptions
(NotConnectedError/SessionExpiredError/ProviderRateLimitedError) instead
of SystemExit, since a SystemExit inside an MCP tool call would kill the
whole server process, not just fail that one call.
"""

from datetime import datetime

from ingest.core import exceptions as ingest_exc
from ingest.core.engine import DataEngine
from ingest.core.models import Bar
from ingest.core.registry import AdapterFactory
from ingest.storage.duckdb_store import DuckDBStore

from engine.core.adapters import ensure_adapters_registered
from engine.core.exceptions import (
    NotConnectedError,
    ProviderRateLimitedError,
    SessionExpiredError,
)
from engine.core.state import load_credentials, load_most_recent


def resolve_provider(explicit_provider: str | None) -> tuple[str, dict[str, object]]:
    """Resolve which provider's stored credentials to use.

    Args:
        explicit_provider: A provider name the caller asked for, or None
            to fall back to whichever provider connected most recently.

    Returns:
        The resolved provider name and its stored credentials.

    Raises:
        NotConnectedError: No adapter is connected yet, or the requested
            provider has no stored session.
    """
    if explicit_provider:
        creds = load_credentials(explicit_provider)
        if creds is None:
            raise NotConnectedError(
                f"no stored session for provider {explicit_provider!r} - run "
                "the connect-adapter skill first."
            )
        return explicit_provider, creds
    most_recent = load_most_recent()
    if most_recent is None:
        raise NotConnectedError(
            "no adapter is connected yet - run the connect-adapter skill first."
        )
    return most_recent


async def connect_engine(provider: str | None) -> tuple[str, DataEngine]:
    """Resolve the provider, build its adapter, connect once, wrap in a DataEngine.

    Args:
        provider: A provider name to use, or None for the most recently
            connected one.

    Returns:
        The resolved provider name and a connected DataEngine.

    Raises:
        NotConnectedError: No stored session.
        SessionExpiredError: The stored session has expired.
        ProviderRateLimitedError: The provider rejected the connect call
            for exceeding its rate limit.
    """
    ensure_adapters_registered()
    resolved_provider, creds = resolve_provider(provider)

    adapter = AdapterFactory.create(resolved_provider, creds)
    try:
        await adapter.connect()
    except ingest_exc.AuthExpiredError:
        raise SessionExpiredError(
            f"the stored {resolved_provider} session has expired - reconnect "
            "via the connect-adapter skill."
        ) from None
    except ingest_exc.RateLimitError as exc:
        raise ProviderRateLimitedError(
            f"{resolved_provider} rate-limited the connect call: {exc}. Wait a "
            "moment and retry."
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
        SessionExpiredError: The session expired mid-fetch.
        ProviderRateLimitedError: The provider rejected the fetch call for
            exceeding its rate limit.
        ingest_exc.DataUnavailableError: No bars exist for the requested
            symbol/range (message includes the reason).
    """
    try:
        bars = await engine.fetch_historical(symbol, interval, frm, to, provider=resolved_provider)
    except ingest_exc.AuthExpiredError:
        raise SessionExpiredError(
            f"the stored {resolved_provider} session has expired - reconnect "
            "via the connect-adapter skill."
        ) from None
    except ingest_exc.RateLimitError as exc:
        raise ProviderRateLimitedError(
            f"{resolved_provider} rate-limited the fetch call: {exc}. Wait a "
            "moment and retry."
        ) from None

    if not bars:
        raise ingest_exc.DataUnavailableError(
            f"no bars found for {symbol!r} in the requested range - try a "
            "different symbol or a wider range."
        )
    return list(bars)
