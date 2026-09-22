"""SandboxBroker: paper trading behind the BrokerPort order methods (ADR 11 in
docs/adr). Prices come from the real broker adapter it wraps; orders, fills,
positions and funds live only in the local sandbox tables. No order ever
reaches the broker.

MARKET orders fill at once at a fresh quote. Resting orders (LIMIT, SL) wait
for the always-on daemon's execution engine and are rejected until then by
`validate_order`.
"""

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime

from openticker.core.orders.models import Order, OrderRequest, OrderResult, OrderStatus
from openticker.core.orders.sandbox import (
    Leverage,
    apply_fill,
    leverage_for,
    quote_is_fillable,
)
from openticker.ports.broker_port import BrokerPort
from openticker.ports.models import (
    Bar,
    Credentials,
    Funds,
    Instrument,
    Position,
    Product,
    Quote,
)
from openticker.storage.sqlite import sandbox_repo
from openticker.storage.sqlite.instruments_repo import get_instrument
from openticker.storage.sqlite.sandbox_repo import StoredOrder


@dataclass(frozen=True)
class SandboxSettings:
    starting_capital: float = 10_000_000.0  # one crore
    leverage: Leverage = field(default_factory=Leverage)


class SandboxBroker:
    def __init__(self, name: str, market: BrokerPort, settings: SandboxSettings) -> None:
        self._name = name
        self._market = market
        self._settings = settings

    # Market data and login pass straight through to the real broker.

    def authenticate(self, request_token: str) -> Credentials:
        return self._market.authenticate(request_token)

    def get_instrument_master(self) -> list[Instrument]:
        return self._market.get_instrument_master()

    def get_quote(self, instrument: Instrument) -> Quote:
        return self._market.get_quote(instrument)

    def get_quotes(self, instruments: Sequence[Instrument]) -> list[Quote]:
        return self._market.get_quotes(instruments)

    def get_historical_bars(
        self, instrument: Instrument, interval: str, start: date, end: date
    ) -> list[Bar]:
        return self._market.get_historical_bars(instrument, interval, start, end)

    # The order side is simulated.

    def place_order(self, request: OrderRequest) -> OrderResult:
        quote = self._market.get_quote(request.instrument)
        placed_at = datetime.now(UTC)
        order = StoredOrder(
            order_id=f"SB{uuid.uuid4().hex[:12].upper()}",
            placed_at=placed_at,
            exchange=request.instrument.exchange.value,
            symbol=request.instrument.symbol,
            side=request.side,
            quantity=request.quantity,
            product=request.product,
            order_type=request.order_type,
            status=OrderStatus.REJECTED,
            fill_price=None,
            reason=None,
            triggered_by=request.triggered_by,
            strategy_id=request.strategy_id,
            run_id=request.run_id,
        )
        with sandbox_repo.fill_transaction() as session:
            reason = self._rejection(request, quote)
            if reason is None:
                price = quote.last_price
                funds = sandbox_repo.load_funds(session, self._settings.starting_capital)
                held = sandbox_repo.load_position(
                    session, order.exchange, order.symbol, request.product
                )
                outcome = apply_fill(
                    held,
                    request.side,
                    request.quantity,
                    price,
                    leverage_for(
                        request.instrument, request.product, request.side, self._settings.leverage
                    ),
                )
                if request.product is Product.CNC and outcome.position.quantity < 0:
                    reason = "delivery (CNC) shares can't be sold short; use MIS to short intraday"
                elif outcome.opened_quantity and outcome.margin_required > (
                    funds.available_cash + outcome.margin_released + outcome.realized_pnl
                ):
                    # Closing is never refused for lack of funds; only the part
                    # that opens a position needs margin.
                    reason = (
                        f"insufficient sandbox funds: needs {outcome.margin_required:,.2f} margin, "
                        f"{funds.available_cash:,.2f} available"
                    )
                else:
                    sandbox_repo.save_position(
                        session, order.exchange, order.symbol, request.product, outcome.position
                    )
                    sandbox_repo.save_funds(
                        session,
                        replace(
                            funds,
                            used_margin=funds.used_margin
                            - outcome.margin_released
                            + outcome.margin_required,
                            realized_pnl=funds.realized_pnl + outcome.realized_pnl,
                        ),
                    )
                    order = replace(order, status=OrderStatus.FILLED, fill_price=price)
            if reason is not None:
                order = replace(order, reason=reason)
            sandbox_repo.record_order(session, order)
        return OrderResult(
            status=order.status,
            broker_order_id=order.order_id,
            reason=order.reason,
            fill_price=order.fill_price,
        )

    def get_positions(self) -> list[Position]:
        stored = [
            (item, instrument)
            for item in sandbox_repo.list_positions()
            if (instrument := get_instrument(item.symbol, item.exchange)) is not None
        ]
        open_instruments = [instrument for item, instrument in stored if item.position.quantity]
        prices = {
            quote.instrument.symbol: quote.last_price
            for quote in (self._market.get_quotes(open_instruments) if open_instruments else [])
            if quote_is_fillable(quote)
        }
        positions: list[Position] = []
        for item, instrument in stored:
            held = item.position
            price = prices.get(instrument.symbol)
            positions.append(
                Position(
                    instrument=instrument,
                    product=item.product,
                    quantity=held.quantity,
                    average_price=held.average_price,
                    last_price=price,
                    realized_pnl=held.realized_pnl,
                    unrealized_pnl=(
                        0.0
                        if held.quantity == 0
                        else (price - held.average_price) * held.quantity
                        if price is not None
                        else None
                    ),
                )
            )
        return positions

    def get_funds(self) -> Funds:
        funds = sandbox_repo.read_funds(self._settings.starting_capital)
        return Funds(
            broker=self._name,
            available_cash=funds.available_cash,
            used_margin=funds.used_margin,
            total_capital=funds.total_capital,
            realized_pnl=funds.realized_pnl,
        )

    def get_orderbook(self, limit: int) -> list[Order]:
        return [
            stored.to_order(instrument)
            for stored in sandbox_repo.list_orders(limit)
            if (instrument := get_instrument(stored.symbol, stored.exchange)) is not None
        ]

    @staticmethod
    def _rejection(request: OrderRequest, quote: Quote) -> str | None:
        if not quote_is_fillable(quote):
            return (
                f"no fresh price for {request.instrument.symbol} (last {quote.last_price}); "
                "not filled"
            )
        return None
