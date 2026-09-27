"""SandboxBroker: paper trading behind the BrokerPort order methods (ADR 11 in
docs/adr). Prices come from the real broker adapter it wraps; orders, fills,
positions and funds live only in the local sandbox tables. No order ever
reaches the broker.

MARKET orders fill at once against a fresh quote's book: a buy at the ask,
a sell at the bid (ADR 28). Every fill pays the brokerage, taxes and fees in
the charges file, kept on its trade and taken from available cash.
LIMIT, SL and SL-M orders rest
as PENDING, with margin set aside for the part that would open a position,
until the daemon's execution engine sees a live price cross them
(`fill_pending`). A LIMIT the market is already through fills at once, as on
an exchange; an SL or SL-M whose trigger is already crossed is refused, as
exchanges refuse it. A pending order's quantity, price and trigger can be
changed (`modify_order`); the margin it holds follows, and it never fills on
the change itself: the next live price decides.
"""

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime

from sqlalchemy.orm import Session

from openticker.core.orders.charge_check import ChargeSample
from openticker.core.orders.charges import ChargeBook, Charges, charges_for
from openticker.core.orders.fills import FillSettings, market_price, marketable_limit_price
from openticker.core.orders.matching import trigger_crossed
from openticker.core.orders.models import (
    Order,
    OrderChanges,
    OrderRequest,
    OrderResult,
    OrderStatus,
    OrderType,
    Trade,
)
from openticker.core.orders.modify import ChangeRefused, apply_changes
from openticker.core.orders.sandbox import (
    Leverage,
    PaperMargin,
    apply_fill,
    leverage_for,
    paper_margin,
    quote_is_fillable,
)
from openticker.ports.broker_port import BrokerPort
from openticker.ports.models import (
    Bar,
    Credentials,
    Funds,
    Instrument,
    MarginRequirement,
    MarketDepth,
    Position,
    Product,
    Quote,
    Side,
)
from openticker.storage.charges_file import load_charge_book
from openticker.storage.sqlite import sandbox_repo
from openticker.storage.sqlite.instruments_repo import get_instrument
from openticker.storage.sqlite.sandbox_repo import FundsState, StoredOrder


@dataclass(frozen=True)
class SandboxSettings:
    starting_capital: float = 10_000_000.0  # one crore
    leverage: Leverage = field(default_factory=Leverage)
    fills: FillSettings = field(default_factory=FillSettings)
    charges: ChargeBook | None = None  # None: the charges file (ADR 28 in docs/adr)


class SandboxBroker:
    def __init__(
        self,
        name: str,
        market: BrokerPort,
        settings: SandboxSettings,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._name = name
        self._market = market
        self._settings = settings
        self._clock = clock
        self._charges = settings.charges if settings.charges is not None else load_charge_book()

    # Market data and login pass straight through to the real broker.

    def authenticate(self, request_token: str) -> Credentials:
        return self._market.authenticate(request_token)

    def get_instrument_master(self) -> list[Instrument]:
        return self._market.get_instrument_master()

    def get_quote(self, instrument: Instrument) -> Quote:
        return self._market.get_quote(instrument)

    def get_quotes(self, instruments: Sequence[Instrument]) -> list[Quote]:
        return self._market.get_quotes(instruments)

    def get_market_depth(self, instrument: Instrument) -> MarketDepth:
        return self._market.get_market_depth(instrument)

    def get_margin(self, orders: Sequence[OrderRequest]) -> MarginRequirement:
        """The broker's figure, not the sandbox's own rule (get_funds)."""
        return self._market.get_margin(orders)

    def get_charges(self, orders: Sequence[ChargeSample]) -> list[Charges]:
        """The broker's contract note, not the sandbox's rates (ADR 28)."""
        return self._market.get_charges(orders)

    def get_historical_bars(
        self, instrument: Instrument, interval: str, start: date, end: date
    ) -> list[Bar]:
        return self._market.get_historical_bars(instrument, interval, start, end)

    # The order side is simulated.

    def place_order(self, request: OrderRequest) -> OrderResult:
        quote = self._market.get_quote(request.instrument)
        order = StoredOrder(
            order_id=f"SB{uuid.uuid4().hex[:12].upper()}",
            placed_at=self._clock(),
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
            price=request.price,
            trigger_price=request.trigger_price,
        )
        fresh = quote_is_fillable(quote)
        price = quote.last_price
        tick = request.instrument.tick_size
        fill_at: float | None = None
        if fresh and request.order_type is OrderType.MARKET:
            fill_at = market_price(request.side, quote, tick, self._settings.fills)
        elif fresh and request.order_type is OrderType.LIMIT and request.price is not None:
            fill_at = marketable_limit_price(
                request.side, request.price, quote, tick, self._settings.fills
            )
        with sandbox_repo.fill_transaction() as session:
            funds = sandbox_repo.load_funds(session, self._settings.starting_capital)
            if request.order_type is OrderType.MARKET or fill_at is not None:
                if fill_at is None:
                    reason: str | None = (
                        f"no fresh price for {order.symbol} (last {price}); not filled"
                    )
                    charges = None
                else:
                    reason, charges = self._fill(session, request.instrument, order, fill_at, funds)
                order = replace(
                    order,
                    status=OrderStatus.REJECTED if reason else OrderStatus.FILLED,
                    fill_price=None if reason else fill_at,
                    reason=reason,
                    charges=charges,
                    expected_price=price,
                )
            elif (
                fresh
                and request.trigger_price is not None
                and trigger_crossed(request.side, request.trigger_price, price)
            ):
                order = replace(
                    order,
                    reason=f"trigger_price {request.trigger_price} is already crossed "
                    f"(last {price}); use a MARKET or LIMIT order",
                )
            else:
                order = self._rest(session, request.instrument, order, funds)
            sandbox_repo.record_order(session, order)
        return _result(order)

    def get_order(self, order_id: str) -> Order | None:
        stored = sandbox_repo.find_order(order_id)
        if stored is None:
            return None
        instrument = get_instrument(stored.symbol, stored.exchange)
        return stored.to_order(instrument) if instrument is not None else None

    def cancel_order(self, order_id: str) -> OrderResult:
        return self.expire_order(order_id, "cancelled", self._clock())

    def pending_orders(self) -> list[Order]:
        return [
            stored.to_order(instrument)
            for stored in sandbox_repo.list_pending_orders()
            if (instrument := get_instrument(stored.symbol, stored.exchange)) is not None
        ]

    def modify_order(self, order_id: str, changes: OrderChanges) -> OrderResult:
        with sandbox_repo.fill_transaction() as session:
            order = sandbox_repo.load_order(session, order_id)
            if order is None or order.status is not OrderStatus.PENDING:
                return _not_pending(order_id, order)
            instrument = get_instrument(order.symbol, order.exchange)
            if instrument is None:
                return _refused(order_id, f"{order.symbol} is no longer in the instrument master")
            try:
                request = apply_changes(order.to_order(instrument), changes)
            except ChangeRefused as exc:
                return _refused(order_id, str(exc))
            changed = replace(
                order,
                quantity=request.quantity,
                price=request.price,
                trigger_price=request.trigger_price,
                # A new trigger has to be crossed again before an SL arms.
                triggered=order.triggered and request.trigger_price == order.trigger_price,
            )
            funds = sandbox_repo.load_funds(session, self._settings.starting_capital)
            funds = replace(funds, used_margin=funds.used_margin - order.reserved_margin)
            reserve = self._reserve(session, instrument, changed, funds)
            if isinstance(reserve, str):
                return _refused(order_id, reserve)
            sandbox_repo.save_funds(
                session, replace(funds, used_margin=funds.used_margin + reserve)
            )
            changed = replace(changed, reserved_margin=reserve)
            sandbox_repo.update_order(session, changed, self._clock())
        return _result(changed)

    def fill_pending(self, pending: Order, price: float, now: datetime) -> OrderResult:
        order_id = pending.order_id
        with sandbox_repo.fill_transaction() as session:
            order = sandbox_repo.load_order(session, order_id)
            if order is None or order.status is not OrderStatus.PENDING:
                return _not_pending(order_id, order)
            if _changed_since(order, pending):
                return _result(replace(order, reason=_CHANGED))
            instrument = get_instrument(order.symbol, order.exchange)
            funds = sandbox_repo.load_funds(session, self._settings.starting_capital)
            funds = replace(funds, used_margin=funds.used_margin - order.reserved_margin)
            if instrument is None:
                reason: str | None = f"{order.symbol} is no longer in the instrument master"
                charges = None
            else:
                reason, charges = self._fill(session, instrument, order, price, funds)
            if reason is not None:
                sandbox_repo.save_funds(session, funds)
            order = replace(
                order,
                status=OrderStatus.REJECTED if reason else OrderStatus.FILLED,
                fill_price=None if reason else price,
                reason=reason,
                reserved_margin=0.0,
                charges=charges,
                expected_price=order.price if order.price is not None else order.trigger_price,
            )
            sandbox_repo.update_order(session, order, now)
        return _result(order)

    def arm_pending(self, pending: Order, now: datetime) -> None:
        with sandbox_repo.fill_transaction() as session:
            order = sandbox_repo.load_order(session, pending.order_id)
            if (
                order is not None
                and order.status is OrderStatus.PENDING
                and not _changed_since(order, pending)
            ):
                sandbox_repo.update_order(session, replace(order, triggered=True), now)

    def expire_order(self, order_id: str, reason: str, now: datetime) -> OrderResult:
        with sandbox_repo.fill_transaction() as session:
            order = sandbox_repo.load_order(session, order_id)
            if order is None or order.status is not OrderStatus.PENDING:
                return _not_pending(order_id, order)
            funds = sandbox_repo.load_funds(session, self._settings.starting_capital)
            sandbox_repo.save_funds(
                session, replace(funds, used_margin=funds.used_margin - order.reserved_margin)
            )
            order = replace(order, status=OrderStatus.CANCELLED, reason=reason, reserved_margin=0.0)
            sandbox_repo.update_order(session, order, now)
        return _result(order)

    def orders_of_run(self, run_id: str) -> list[Order]:
        return [
            stored.to_order(instrument)
            for stored in sandbox_repo.list_run_orders(run_id)
            if (instrument := get_instrument(stored.symbol, stored.exchange)) is not None
        ]

    def open_positions(self) -> list[Position]:
        return [
            Position(
                instrument=instrument,
                product=item.product,
                quantity=item.position.quantity,
                average_price=item.position.average_price,
                last_price=None,
                realized_pnl=item.position.realized_pnl,
                unrealized_pnl=None,
            )
            for item in sandbox_repo.list_positions()
            if item.position.quantity
            and (instrument := get_instrument(item.symbol, item.exchange)) is not None
        ]

    def settle_position(
        self, instrument: Instrument, product: Product, price: float, reason: str, now: datetime
    ) -> OrderResult:
        """At the settlement price, with no charges: exercise and assignment
        charges are not modelled (ADR 28 in docs/adr)."""
        return self._close(
            instrument, product, lambda side: price, price, False, reason, SETTLEMENT_TRIGGER, now
        )

    def close_position(
        self,
        instrument: Instrument,
        product: Product,
        quote: Quote,
        now: datetime,
        triggered_by: str,
    ) -> OrderResult:
        """At the market: the bid when selling what is held, the ask when
        buying back a short."""

        def at_market(side: Side) -> float:
            return market_price(side, quote, instrument.tick_size, self._settings.fills)

        return self._close(
            instrument, product, at_market, quote.last_price, True, None, triggered_by, now
        )

    def _close(
        self,
        instrument: Instrument,
        product: Product,
        price_for: Callable[[Side], float],
        expected_price: float,
        charged: bool,
        reason: str | None,
        triggered_by: str,
        now: datetime,
    ) -> OrderResult:
        """A MARKET order for exactly what is held, read under the write lock:
        a resting order filling meanwhile can't make it overshoot."""
        with sandbox_repo.fill_transaction() as session:
            exchange = instrument.exchange.value
            held = sandbox_repo.load_position(session, exchange, instrument.symbol, product)
            if held.quantity == 0:
                return OrderResult(
                    status=OrderStatus.REJECTED,
                    broker_order_id=None,
                    reason=f"no open {product} position in {instrument.symbol}",
                )
            side = Side.SELL if held.quantity > 0 else Side.BUY
            quantity = abs(held.quantity)
            price = price_for(side)
            charges = (
                self._charges_of(instrument, product, side, quantity, price) if charged else None
            )
            order = StoredOrder(
                order_id=f"SB{uuid.uuid4().hex[:12].upper()}",
                placed_at=now,
                exchange=exchange,
                symbol=instrument.symbol,
                side=side,
                quantity=quantity,
                product=product,
                order_type=OrderType.MARKET,
                status=OrderStatus.FILLED,
                fill_price=price,
                reason=reason,
                triggered_by=triggered_by,
                strategy_id=None,
                run_id=None,
                charges=charges,
                expected_price=expected_price,
            )
            funds = sandbox_repo.load_funds(session, self._settings.starting_capital)
            outcome = apply_fill(
                held,
                side,
                quantity,
                price,
                leverage_for(instrument, product, side, self._settings.leverage),
            )
            sandbox_repo.save_position(
                session, exchange, instrument.symbol, product, outcome.position
            )
            sandbox_repo.save_funds(
                session,
                replace(
                    funds,
                    used_margin=funds.used_margin - outcome.margin_released,
                    realized_pnl=funds.realized_pnl + outcome.realized_pnl,
                    charges=funds.charges + (charges or 0.0),
                ),
            )
            sandbox_repo.record_order(session, order)
        return _result(order)

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
            charges=funds.charges,
        )

    def preview_margin(
        self, instrument: Instrument, side: Side, quantity: int, product: Product, price: float
    ) -> PaperMargin:
        """What a fill of this order at `price` would block and free, against
        the position held: the sandbox's own rule, not the broker's (get_margin)."""
        held = sandbox_repo.read_position(instrument.exchange.value, instrument.symbol, product)
        funds = sandbox_repo.read_funds(self._settings.starting_capital)
        leverage = leverage_for(instrument, product, side, self._settings.leverage)
        return paper_margin(held, side, quantity, price, leverage, funds.available_cash)

    def get_orderbook(self, limit: int) -> list[Order]:
        return [
            stored.to_order(instrument)
            for stored in sandbox_repo.list_orders(limit)
            if (instrument := get_instrument(stored.symbol, stored.exchange)) is not None
        ]

    def get_trades(self, since: datetime, limit: int) -> list[Trade]:
        return [
            stored.to_trade(instrument)
            for stored in sandbox_repo.list_trades(since, limit)
            if (instrument := get_instrument(stored.symbol, stored.exchange)) is not None
        ]

    def _fill(
        self,
        session: Session,
        instrument: Instrument,
        order: StoredOrder,
        price: float,
        funds: FundsState,
    ) -> tuple[str | None, float | None]:
        """Applies the fill and its charges to position and funds: why it
        can't, or None and the charges paid (None when the charges file has
        no schedule for it)."""
        held = sandbox_repo.load_position(session, order.exchange, order.symbol, order.product)
        outcome = apply_fill(
            held,
            order.side,
            order.quantity,
            price,
            leverage_for(instrument, order.product, order.side, self._settings.leverage),
        )
        if order.product is Product.CNC and outcome.position.quantity < 0:
            return _CNC_SHORT, None
        charges = self._charges_of(instrument, order.product, order.side, order.quantity, price)
        # Closing is never refused for lack of funds; only the part that opens
        # a position needs margin.
        if outcome.opened_quantity and outcome.margin_required > (
            funds.available_cash + outcome.margin_released + outcome.realized_pnl
        ):
            return _insufficient(outcome.margin_required, funds.available_cash), None
        sandbox_repo.save_position(
            session, order.exchange, order.symbol, order.product, outcome.position
        )
        sandbox_repo.save_funds(
            session,
            replace(
                funds,
                used_margin=funds.used_margin - outcome.margin_released + outcome.margin_required,
                realized_pnl=funds.realized_pnl + outcome.realized_pnl,
                charges=funds.charges + (charges or 0.0),
            ),
        )
        return None, charges

    def _charges_of(
        self, instrument: Instrument, product: Product, side: Side, quantity: int, price: float
    ) -> float | None:
        schedule = self._charges.for_fill(instrument, product)
        return charges_for(schedule, side, quantity, price).total if schedule else None

    def _rest(
        self, session: Session, instrument: Instrument, order: StoredOrder, funds: FundsState
    ) -> StoredOrder:
        """A PENDING order holding margin for what it would open, valued at
        its limit (or trigger, for SL-M)."""
        reserve = self._reserve(session, instrument, order, funds)
        if isinstance(reserve, str):
            return replace(order, reason=reserve)
        sandbox_repo.save_funds(session, replace(funds, used_margin=funds.used_margin + reserve))
        return replace(order, status=OrderStatus.PENDING, reserved_margin=reserve)

    def _reserve(
        self, session: Session, instrument: Instrument, order: StoredOrder, funds: FundsState
    ) -> float | str:
        """The margin a resting order holds, or why the funds can't cover it."""
        reference = order.price if order.price is not None else order.trigger_price
        assert reference is not None  # validate_order: every resting type has one
        held = sandbox_repo.load_position(session, order.exchange, order.symbol, order.product)
        outcome = apply_fill(
            held,
            order.side,
            order.quantity,
            reference,
            leverage_for(instrument, order.product, order.side, self._settings.leverage),
        )
        if order.product is Product.CNC and outcome.position.quantity < 0:
            return _CNC_SHORT
        if outcome.margin_required > funds.available_cash:
            return _insufficient(outcome.margin_required, funds.available_cash)
        return outcome.margin_required


SETTLEMENT_TRIGGER = "expiry-settlement"
_CHANGED = "changed since this price was matched; the next price decides"
_CNC_SHORT = "delivery (CNC) shares can't be sold short; use MIS to short intraday"


def _insufficient(needed: float, available: float) -> str:
    return f"insufficient sandbox funds: needs {needed:,.2f} margin, {available:,.2f} available"


def _result(order: StoredOrder) -> OrderResult:
    return OrderResult(
        status=order.status,
        broker_order_id=order.order_id,
        reason=order.reason,
        fill_price=order.fill_price,
    )


def _refused(order_id: str, reason: str) -> OrderResult:
    """A change not made: the order stays as it was."""
    return OrderResult(status=OrderStatus.REJECTED, broker_order_id=order_id, reason=reason)


def _changed_since(order: StoredOrder, seen: Order) -> bool:
    return (order.quantity, order.price, order.trigger_price) != (
        seen.quantity,
        seen.price,
        seen.trigger_price,
    )


def _not_pending(order_id: str, order: StoredOrder | None) -> OrderResult:
    if order is None:
        return OrderResult(
            status=OrderStatus.REJECTED,
            broker_order_id=order_id,
            reason=f"no sandbox order {order_id}",
        )
    return OrderResult(
        status=order.status,
        broker_order_id=order_id,
        reason=f"order {order_id} is already {order.status}; nothing to change",
        fill_price=order.fill_price,
    )
