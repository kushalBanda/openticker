from collections.abc import AsyncIterator
from datetime import datetime
from typing import Protocol

from data_engine.core.models import Bar, Tick


class MarketDataAdapter(Protocol):
    async def connect(self) -> None: ...

    async def fetch_historical(
        self, symbol: str, interval: str, from_: datetime, to: datetime
    ) -> list[Bar]: ...

    def subscribe_live(self, symbols: list[str]) -> AsyncIterator[Tick]: ...

    async def disconnect(self) -> None: ...
