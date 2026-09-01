import csv
import io
from datetime import UTC, date, datetime
from http import HTTPStatus

import httpx

from data_engine.core.constants import (
    INSTRUMENT_MASTER_REFRESH_HOURS,
    KITE_BASE_URL,
    kite_auth_headers,
)
from data_engine.core.exceptions import AuthExpiredError, DataUnavailableError

_INSTRUMENTS_URL = f"{KITE_BASE_URL}/instruments"


class InstrumentMaster:
    def __init__(
        self,
        api_key: str,
        access_token: str,
        http_client: httpx.AsyncClient,
        refresh_interval_hours: int = INSTRUMENT_MASTER_REFRESH_HOURS,
    ) -> None:
        self._api_key = api_key
        self._access_token = access_token
        self._http = http_client
        self._refresh_interval_hours = refresh_interval_hours
        self._tokens_by_symbol: dict[str, int] = {}
        self._last_refreshed: datetime | None = None

    async def refresh(self) -> None:
        response = await self._http.get(
            _INSTRUMENTS_URL,
            headers=kite_auth_headers(self._api_key, self._access_token),
        )
        if response.status_code == HTTPStatus.FORBIDDEN:
            raise AuthExpiredError("Kite session expired while fetching instrument master")
        response.raise_for_status()

        reader = csv.DictReader(io.StringIO(response.text))
        tokens_by_symbol: dict[str, int] = {}
        for row in reader:
            tokens_by_symbol[row["tradingsymbol"]] = int(row["instrument_token"])

        self._tokens_by_symbol = tokens_by_symbol
        self._last_refreshed = datetime.now(UTC)

    def resolve(self, tradingsymbol: str) -> int:
        try:
            return self._tokens_by_symbol[tradingsymbol]
        except KeyError:
            raise DataUnavailableError(
                f"{tradingsymbol!r} not found in Kite instrument master"
            ) from None

    def last_refreshed(self) -> date | None:
        return self._last_refreshed.date() if self._last_refreshed else None
