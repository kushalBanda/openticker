import httpx
import pytest
import respx
from data_engine.adapters.kite.instrument_master import InstrumentMaster
from data_engine.core.constants import KITE_BASE_URL
from data_engine.core.exceptions import AuthExpiredError, DataUnavailableError

_CSV_BODY = (
    "instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,"
    "strike,tick_size,lot_size,instrument_type,segment,exchange\n"
    "128083204,500325,RELIANCE,RELIANCE INDUSTRIES,0,,0,0.05,1,EQ,NSE,NSE\n"
)


@respx.mock
async def test_resolve_after_refresh() -> None:
    respx.get(f"{KITE_BASE_URL}/instruments").mock(
        return_value=httpx.Response(200, text=_CSV_BODY)
    )
    async with httpx.AsyncClient() as client:
        master = InstrumentMaster(
            api_key="key", access_token="token", http_client=client
        )
        await master.refresh()
        assert master.resolve("RELIANCE") == 128083204
        assert master.last_refreshed() is not None


@respx.mock
async def test_resolve_unknown_symbol_raises() -> None:
    respx.get(f"{KITE_BASE_URL}/instruments").mock(
        return_value=httpx.Response(200, text=_CSV_BODY)
    )
    async with httpx.AsyncClient() as client:
        master = InstrumentMaster(
            api_key="key", access_token="token", http_client=client
        )
        await master.refresh()
        with pytest.raises(DataUnavailableError):
            master.resolve("UNKNOWN_SYMBOL")


@respx.mock
async def test_refresh_raises_auth_expired_on_403() -> None:
    respx.get(f"{KITE_BASE_URL}/instruments").mock(return_value=httpx.Response(403))
    async with httpx.AsyncClient() as client:
        master = InstrumentMaster(
            api_key="key", access_token="expired", http_client=client
        )
        with pytest.raises(AuthExpiredError):
            await master.refresh()
