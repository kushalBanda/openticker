import asyncio
from datetime import UTC, datetime
from typing import Any, ClassVar
from unittest.mock import patch

import pytest
from data_engine.adapters.groww.adapter import GrowwAdapter
from data_engine.core.exceptions import (
    AuthExpiredError,
    DataUnavailableError,
    RateLimitError,
)
from growwapi import GrowwAPI
from growwapi.groww.exceptions import (
    GrowwAPIAuthenticationException,
    GrowwAPINotFoundException,
    GrowwAPIRateLimitException,
)

_HISTORICAL_RESPONSE: dict[str, Any] = {
    "candles": [
        [1735718400, 100.0, 105.0, 99.0, 104.0, 1000],
        [1735804800, 104.0, 108.0, 103.0, 107.0, 1200],
    ]
}


async def test_groww_adapter_fetch_historical_happy_path() -> None:
    with (
        patch.object(GrowwAPI, "get_access_token", return_value="fake-token"),
        patch.object(
            GrowwAPI, "get_historical_candles", return_value=_HISTORICAL_RESPONSE
        ),
    ):
        adapter = GrowwAdapter(api_key="key", totp_secret="JBSWY3DPEHPK3PXP")
        await adapter.connect()

        bars = await adapter.fetch_historical(
            "RELIANCE",
            "1d",
            datetime(2026, 1, 1, tzinfo=UTC),
            datetime(2026, 1, 4, tzinfo=UTC),
        )

    assert len(bars) == 2
    assert bars[0].close == 104.0
    assert bars[0].provider == "groww"
    await adapter.disconnect()


async def test_groww_adapter_fetch_historical_auth_expired() -> None:
    with (
        patch.object(GrowwAPI, "get_access_token", return_value="fake-token"),
        patch.object(
            GrowwAPI,
            "get_historical_candles",
            side_effect=GrowwAPIAuthenticationException(),
        ),
    ):
        adapter = GrowwAdapter(api_key="key", totp_secret="JBSWY3DPEHPK3PXP")
        await adapter.connect()

        with pytest.raises(AuthExpiredError):
            await adapter.fetch_historical(
                "RELIANCE",
                "1d",
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2026, 1, 4, tzinfo=UTC),
            )
    await adapter.disconnect()


async def test_groww_adapter_fetch_historical_rate_limited() -> None:
    with (
        patch.object(GrowwAPI, "get_access_token", return_value="fake-token"),
        patch.object(
            GrowwAPI,
            "get_historical_candles",
            side_effect=GrowwAPIRateLimitException(),
        ),
    ):
        adapter = GrowwAdapter(api_key="key", totp_secret="JBSWY3DPEHPK3PXP")
        await adapter.connect()

        with pytest.raises(RateLimitError):
            await adapter.fetch_historical(
                "RELIANCE",
                "1d",
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2026, 1, 4, tzinfo=UTC),
            )
    await adapter.disconnect()


async def test_groww_adapter_fetch_historical_generic_error_wrapped() -> None:
    with (
        patch.object(GrowwAPI, "get_access_token", return_value="fake-token"),
        patch.object(
            GrowwAPI,
            "get_historical_candles",
            side_effect=GrowwAPINotFoundException(),
        ),
    ):
        adapter = GrowwAdapter(api_key="key", totp_secret="JBSWY3DPEHPK3PXP")
        await adapter.connect()

        with pytest.raises(DataUnavailableError):
            await adapter.fetch_historical(
                "NOT_A_REAL_SYMBOL",
                "1d",
                datetime(2026, 1, 1, tzinfo=UTC),
                datetime(2026, 1, 4, tzinfo=UTC),
            )
    await adapter.disconnect()
