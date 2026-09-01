from collections.abc import AsyncIterator
from datetime import datetime

from data_engine.core.exceptions import DataUnavailableError
from data_engine.core.interfaces import MarketDataAdapter
from data_engine.core.models import Bar, Tick
from data_engine.storage.duckdb_store import DuckDBStore


class DataEngine:
    def __init__(
        self,
        adapters: dict[str, MarketDataAdapter],
        store: DuckDBStore,
        provider_routes: dict[str, str] | None = None,
    ) -> None:
        self._adapters = adapters
        self._store = store
        self._provider_routes = provider_routes or {}

    def _resolve_provider(self, symbol: str, provider: str | None) -> str:
        if provider is not None:
            return provider
        try:
            return self._provider_routes[symbol]
        except KeyError:
            raise DataUnavailableError(
                f"no provider route configured for {symbol!r}, "
                "pass an explicit provider= or add it to providers.yaml"
            ) from None

    async def fetch_historical(
        self,
        symbol: str,
        interval: str,
        from_: datetime,
        to: datetime,
        provider: str | None = None,
    ) -> list[Bar]:
        resolved_provider = self._resolve_provider(symbol, provider)
        gaps = self._store.find_missing_range(symbol, interval, from_, to)
        if gaps:
            adapter = self._adapters[resolved_provider]
            for gap_from, gap_to in gaps:
                fetched = await adapter.fetch_historical(symbol, interval, gap_from, gap_to)
                self._store.write_bars(fetched)
        return self._store.query_bars(symbol, interval, from_, to)

    async def subscribe_live(
        self, symbols: list[str], provider: str | None = None
    ) -> AsyncIterator[Tick]:
        resolved_provider = provider or next(iter(self._adapters))
        adapter = self._adapters[resolved_provider]
        async for tick in adapter.subscribe_live(symbols):
            self._store.write_tick(tick)
            yield tick
