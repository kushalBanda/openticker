from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from lib.mechanics.exceptions import DataUnavailableError
from lib.mechanics.nse_index import (
    CACHE_MAX_AGE,
    INDEX_NIFTY_50,
    NseIndexCache,
    _parse_constituent_csv,
    fetch_index_constituents,
)

_SAMPLE_CSV = (
    "Company Name,Industry,Symbol,Series,ISIN Code\n"
    "Reliance Industries Ltd.,Energy,RELIANCE,EQ,INE002A01018\n"
    "Tata Consultancy Services Ltd.,IT,TCS,EQ,INE467B01029\n"
)


def test_parse_constituent_csv_extracts_symbols() -> None:
    symbols = _parse_constituent_csv(_SAMPLE_CSV)
    assert symbols == ["RELIANCE", "TCS"]


def test_parse_constituent_csv_raises_on_empty_data() -> None:
    with pytest.raises(DataUnavailableError):
        _parse_constituent_csv("Company Name,Industry,Symbol,Series,ISIN Code\n")


def test_cache_round_trip(tmp_path: Path) -> None:
    cache = NseIndexCache(db_path=tmp_path / "nse_cache.duckdb")
    assert cache.read_cached(INDEX_NIFTY_50) is None
    fetched_at = datetime.now(UTC)
    cache.write_cache(INDEX_NIFTY_50, ["RELIANCE", "TCS"], fetched_at)
    result = cache.read_cached(INDEX_NIFTY_50)
    assert result is not None
    symbols, cached_at = result
    assert sorted(symbols) == ["RELIANCE", "TCS"]
    assert cached_at == fetched_at


@pytest.mark.asyncio
async def test_fetch_index_constituents_uses_fresh_cache_without_network(tmp_path: Path) -> None:
    cache = NseIndexCache(db_path=tmp_path / "nse_cache.duckdb")
    cache.write_cache(INDEX_NIFTY_50, ["RELIANCE"], datetime.now(UTC))
    symbols = await fetch_index_constituents(INDEX_NIFTY_50, cache=cache)
    assert symbols == ["RELIANCE"]


@pytest.mark.asyncio
async def test_fetch_index_constituents_refetches_when_cache_stale(tmp_path: Path, respx_mock) -> None:  # type: ignore[no-untyped-def]
    cache = NseIndexCache(db_path=tmp_path / "nse_cache.duckdb")
    stale_time = datetime.now(UTC) - CACHE_MAX_AGE - timedelta(hours=1)
    cache.write_cache(INDEX_NIFTY_50, ["OLD"], stale_time)
    respx_mock.get("https://archives.nseindia.com/content/indices/ind_nifty50list.csv").mock(
        return_value=httpx.Response(200, text=_SAMPLE_CSV)
    )
    symbols = await fetch_index_constituents(INDEX_NIFTY_50, cache=cache)
    assert symbols == ["RELIANCE", "TCS"]


@pytest.mark.asyncio
async def test_fetch_index_constituents_rejects_unknown_index() -> None:
    with pytest.raises(ValueError):
        await fetch_index_constituents("not_a_real_index")
