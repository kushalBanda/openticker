"""ZerodhaAdapter — BrokerPort over Kite Connect."""

from datetime import date

from openticker.adapters.brokers.zerodha.auth import exchange_request_token
from openticker.adapters.brokers.zerodha.instruments import (
    download_instrument_csv,
    parse_instrument_csv,
)
from openticker.adapters.brokers.zerodha.market_data import (
    KiteSessionError,
    fetch_candles,
    fetch_quote,
)
from openticker.core.orders.models import OrderRequest, OrderResult
from openticker.ports.models import Bar, Credentials, Funds, Instrument, Position, Quote


class ZerodhaAdapter:
    def __init__(self, api_key: str, api_secret: str, access_token: str | None = None) -> None:
        """`access_token` is None until the broker has been connected
        (`connect_broker`); only the calls that need a session check for it."""
        self._api_key = api_key
        self._api_secret = api_secret
        self._access_token = access_token

    def _session_token(self) -> str:
        if self._access_token is None:
            raise KiteSessionError(
                "zerodha is not connected — call get_broker_login_url, then connect_broker"
            )
        return self._access_token

    def authenticate(self, request_token: str) -> Credentials:
        return exchange_request_token(self._api_key, self._api_secret, request_token)

    def get_instrument_master(self) -> list[Instrument]:
        return parse_instrument_csv(download_instrument_csv())

    def get_quote(self, instrument: Instrument) -> Quote:
        return fetch_quote(self._api_key, self._session_token(), instrument)

    def get_historical_bars(
        self, instrument: Instrument, interval: str, start: date, end: date
    ) -> list[Bar]:
        return fetch_candles(
            self._api_key, self._session_token(), instrument, interval, start, end
        )

    def place_order(self, request: OrderRequest) -> OrderResult:
        raise NotImplementedError("sandbox order placement is not implemented yet")

    def get_positions(self) -> list[Position]:
        raise NotImplementedError("sandbox order placement is not implemented yet")

    def get_funds(self) -> Funds:
        raise NotImplementedError("sandbox order placement is not implemented yet")
