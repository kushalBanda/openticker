from datetime import datetime

from fastapi import APIRouter, Depends, Query
from ingest.core.engine import DataEngine

from server.core.constants import API_PREFIX_MARKET, DEFAULT_INTERVAL
from server.core.deps import get_data_engine
from server.schemas.market import BarListOut, BarOut

router = APIRouter(prefix=API_PREFIX_MARKET, tags=["market"])


@router.get("/bars", response_model=BarListOut)
async def get_bars(
    symbol: str,
    from_: datetime = Query(..., alias="from"),
    to: datetime = Query(...),
    interval: str = DEFAULT_INTERVAL,
    engine: DataEngine = Depends(get_data_engine),
) -> BarListOut:
    # Fetches only what's missing from the provider and caches it.
    bars = await engine.fetch_historical(symbol, interval, from_, to)
    return BarListOut(
        bars=[
            BarOut(
                symbol=b.symbol,
                interval=b.interval,
                ts=b.ts,
                open=b.open,
                high=b.high,
                low=b.low,
                close=b.close,
                volume=b.volume,
                provider=b.provider,
            )
            for b in bars
        ]
    )
