from datetime import UTC, datetime

import httpx
import pytest

from lib.mechanics.kite import KITE_INTERVAL_MAP, fetch_kite_historical


def test_interval_map_covers_1d_and_1m() -> None:
    assert KITE_INTERVAL_MAP["1d"] == "day"
    assert KITE_INTERVAL_MAP["1m"] == "minute"


@pytest.mark.asyncio
async def test_fetch_kite_historical_maps_candles(respx_mock) -> None:  # type: ignore[no-untyped-def]
    respx_mock.get("https://api.kite.trade/instruments").mock(
        return_value=httpx.Response(
            200, text="instrument_token,tradingsymbol\n128083204,RELIANCE\n"
        )
    )
    respx_mock.get(
        "https://api.kite.trade/instruments/historical/128083204/day"
    ).mock(
        return_value=httpx.Response(
            200,
            json={
                "data": {
                    "candles": [
                        ["2017-12-15T09:15:00+0000", 100.5, 105.0, 99.0, 104.25, 12345],
                    ]
                }
            },
        )
    )

    bars = await fetch_kite_historical(
        api_key="key",
        access_token="token",
        symbol="RELIANCE",
        interval="1d",
        frm=datetime(2017, 12, 1, tzinfo=UTC),
        to=datetime(2017, 12, 31, tzinfo=UTC),
    )

    assert len(bars) == 1
    bar = bars[0]
    assert bar.symbol == "RELIANCE"
    assert bar.interval == "1d"
    assert bar.ts == datetime(2017, 12, 15, 9, 15, tzinfo=UTC)
    assert bar.open == 100.5
    assert bar.high == 105.0
    assert bar.low == 99.0
    assert bar.close == 104.25
    assert bar.volume == 12345
    assert bar.provider == "kite"
