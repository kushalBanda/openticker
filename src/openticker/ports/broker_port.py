from collections.abc import Sequence
from datetime import date
from typing import Protocol

from openticker.core.orders.models import OrderRequest, OrderResult
from openticker.ports.models import Bar, Credentials, Funds, Instrument, Position, Quote


class BrokerPort(Protocol):
    def authenticate(self, request_token: str) -> Credentials: ...
    def get_instrument_master(self) -> list[Instrument]: ...
    def get_quote(self, instrument: Instrument) -> Quote: ...
    def get_quotes(self, instruments: Sequence[Instrument]) -> list[Quote]:
        """One quote per instrument that has one, in any order; an instrument
        the broker returns nothing for is left out rather than failing the batch."""
        ...
    def get_historical_bars(
        self, instrument: Instrument, interval: str, start: date, end: date
    ) -> list[Bar]: ...
    def place_order(
        self, request: OrderRequest
    ) -> OrderResult: ...  # sandbox-only (ADR 6 in docs/adr)
    def get_positions(self) -> list[Position]: ...
    def get_funds(self) -> Funds: ...
