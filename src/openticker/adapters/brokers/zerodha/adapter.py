"""ZerodhaAdapter — BrokerPort over Kite Connect."""

from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime

from openticker.adapters.brokers.zerodha.auth import exchange_request_token
from openticker.adapters.brokers.zerodha.charges import fetch_charges
from openticker.adapters.brokers.zerodha.instruments import (
    download_instrument_csv,
    parse_instrument_csv,
)
from openticker.adapters.brokers.zerodha.margins import fetch_margin
from openticker.adapters.brokers.zerodha.market_data import (
    KiteSessionError,
    fetch_candles,
    fetch_depth,
    fetch_quote,
    fetch_quotes,
)
from openticker.core.orders.charge_check import ChargeSample
from openticker.core.orders.charges import Charges
from openticker.core.orders.models import Order, OrderChanges, OrderRequest, OrderResult, Trade
from openticker.ports.models import (
    Bar,
    Credentials,
    Funds,
    Instrument,
    MarginRequirement,
    MarketDepth,
    Position,
    Quote,
)


class ZerodhaAdapter:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        access_token: str | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        """`access_token` is None until the broker has been connected
        (`connect_broker`); only the calls that need a session check for it.
        `clock` dates a login, for when Kite will log it out."""
        self._api_key = api_key
        self._clock = clock
        self._api_secret = api_secret
        self._access_token = access_token

    def _session_token(self) -> str:
        if self._access_token is None:
            raise KiteSessionError(
                "zerodha is not connected — call get_broker_login_url, then connect_broker"
            )
        return self._access_token

    def authenticate(self, request_token: str) -> Credentials:
        return exchange_request_token(self._api_key, self._api_secret, request_token, self._clock())

    def get_instrument_master(self) -> list[Instrument]:
        return parse_instrument_csv(download_instrument_csv())

    def get_quote(self, instrument: Instrument) -> Quote:
        return fetch_quote(self._api_key, self._session_token(), instrument)

    def get_quotes(self, instruments: Sequence[Instrument]) -> list[Quote]:
        return fetch_quotes(self._api_key, self._session_token(), instruments)

    def get_market_depth(self, instrument: Instrument) -> MarketDepth:
        return fetch_depth(self._api_key, self._session_token(), instrument)

    def get_margin(self, orders: Sequence[OrderRequest]) -> MarginRequirement:
        return fetch_margin(self._api_key, self._session_token(), orders)

    def get_charges(self, orders: Sequence[ChargeSample]) -> list[Charges]:
        return fetch_charges(self._api_key, self._session_token(), orders)

    def get_historical_bars(
        self, instrument: Instrument, interval: str, start: date, end: date
    ) -> list[Bar]:
        return fetch_candles(self._api_key, self._session_token(), instrument, interval, start, end)

    # Live orders are not implemented: orders go through the sandbox, which
    # uses this adapter for prices only (ADR 11 in docs/adr).
    def place_order(self, request: OrderRequest) -> OrderResult:
        raise NotImplementedError("live order placement is not implemented yet")

    def get_positions(self) -> list[Position]:
        raise NotImplementedError("live positions are not implemented yet")

    def get_funds(self) -> Funds:
        raise NotImplementedError("live funds are not implemented yet")

    def get_orderbook(self, limit: int) -> list[Order]:
        raise NotImplementedError("the live order book is not implemented yet")

    def get_order(self, order_id: str) -> Order | None:
        raise NotImplementedError("live order lookup is not implemented yet")

    def cancel_order(self, order_id: str) -> OrderResult:
        raise NotImplementedError("live order cancellation is not implemented yet")

    def modify_order(self, order_id: str, changes: OrderChanges) -> OrderResult:
        raise NotImplementedError("live order changes are not implemented yet")

    def get_trades(self, since: datetime, limit: int) -> list[Trade]:
        raise NotImplementedError("the live trade book is not implemented yet")
