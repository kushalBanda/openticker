from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from ingest.core.constants import KNOWN_INDICES, SOURCE_NSE_CSV
from ingest.core.engine import DataEngine
from ingest.core.index_constituents import fetch_index_constituents
from ingest.core.models import IndexConstituent
from ingest.storage.duckdb_store import DuckDBStore

from server.core.constants import API_PREFIX_MARKET, DEFAULT_INTERVAL
from server.core.deps import get_data_engine, get_duckdb_store, get_session
from server.core.security import Session
from server.schemas.market import BarListOut, BarOut, IndexConstituentsOut

router = APIRouter(prefix=API_PREFIX_MARKET, tags=["market"])


@router.get("/bars", response_model=BarListOut)
async def get_bars(
    symbol: str,
    from_: datetime = Query(..., alias="from"),
    to: datetime = Query(...),
    interval: str = DEFAULT_INTERVAL,
    session: Session = Depends(get_session),
    engine: DataEngine = Depends(get_data_engine),
) -> BarListOut:
    # Checks DuckDB first regardless of provider; fetches only what's
    # missing, from whichever provider the caller's session logged in with.
    bars = await engine.fetch_historical(
        symbol, interval, from_, to, provider=session["provider"]
    )
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


@router.post("/index-constituents/{index_name}/fetch", response_model=IndexConstituentsOut)
async def refresh_index_constituents(
    index_name: str,
    _session: Session = Depends(get_session),
    store: DuckDBStore = Depends(get_duckdb_store),
) -> IndexConstituentsOut:
    # Pulls NSE's live constituent CSV for this index and stores it as this
    # year's snapshot. NSE has no historical-by-year endpoint, so every
    # fetch is always tagged with the current year, never a past one.
    if index_name not in KNOWN_INDICES:
        raise ValueError(f"unknown index_name: {index_name!r}")
    symbols = await fetch_index_constituents(index_name)
    year = datetime.now(UTC).year
    store.write_index_constituents(
        [
            IndexConstituent(
                index_name=index_name, symbol=symbol, year=year, source=SOURCE_NSE_CSV
            )
            for symbol in symbols
        ]
    )
    return IndexConstituentsOut(index_name=index_name, year=year, symbols=symbols)


@router.get("/index-constituents", response_model=IndexConstituentsOut)
async def get_index_constituents(
    index_name: str,
    year: int,
    _session: Session = Depends(get_session),
    store: DuckDBStore = Depends(get_duckdb_store),
) -> IndexConstituentsOut:
    symbols = store.query_index_constituents(index_name, year)
    return IndexConstituentsOut(index_name=index_name, year=year, symbols=symbols)
