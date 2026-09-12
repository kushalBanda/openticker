from datetime import UTC, datetime

from ingest.core.models import Bar, Tick

from strategy.core.constants import (
    DEFAULT_COMMISSION_PER_SHARE,
    DEFAULT_SLIPPAGE_BPS,
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_OPEN,
    ORDER_STATUS_RECONCILING,
    ORDER_STATUS_SUBMITTING,
)
from strategy.core.cost_model import (
    BpsSlippageModel,
    PerShareFeeModel,
    SlippageModel,
    TransactionCostModel,
)
from strategy.core.exceptions import OrderNotCancellableError, UnknownOrderError
from strategy.core.models import Fill, Order, OrderState
from strategy.storage.order_store import OrderStore


class PaperBroker:
    """Fills market orders against a live tick stream instead of historical
    bars - see ingest.core.engine.DataEngine.subscribe_live for the tick
    source. Every status transition is written to `OrderStore` before it
    takes effect in memory (write-ahead), so a crash mid-flight leaves a
    durable trail a restart can resume from via `resume_from_store()`.

    Unlike BacktestBroker, PaperBroker is not driven by BacktestEngine's
    bar-batch loop - match_pending_orders is not supported here, orders
    fill through on_tick as ticks arrive for their symbol.
    """

    def __init__(
        self,
        order_store: OrderStore,
        cost_model: TransactionCostModel | None = None,
        slippage_model: SlippageModel | None = None,
    ) -> None:
        self._store = order_store
        self._cost_model = cost_model or PerShareFeeModel(DEFAULT_COMMISSION_PER_SHARE)
        self._slippage_model = slippage_model or BpsSlippageModel(DEFAULT_SLIPPAGE_BPS)
        self._open_orders: dict[str, Order] = {}
        self._fills_by_order: dict[str, list[Fill]] = {}

    async def resume_from_store(self) -> None:
        """Reload every non-terminal order from a prior run into memory.

        Call once at startup, before accepting new orders. PaperBroker has
        no external broker order book to reconcile against - its own store
        is the only source of truth - so a resumed order is simply put back
        into `_open_orders`, marked RECONCILING first to make it visible in
        the store that it survived a restart rather than a normal fill path.
        """
        for state in self._store.list_non_terminal():
            order = state.order
            self._open_orders[order.order_id] = order
            self._store.write_state(
                OrderState(order=order, status=ORDER_STATUS_RECONCILING),
                updated_ts=datetime.now(UTC),
            )

    async def submit_order(self, order: Order) -> OrderState:
        now = datetime.now(UTC)
        self._store.write_state(
            OrderState(order=order, status=ORDER_STATUS_SUBMITTING), updated_ts=now
        )
        # No real broker round-trip to await here - PaperBroker's
        # "acceptance" is immediate. LiveBroker's submit_order does the
        # equivalent Kite API call between these two writes.
        self._open_orders[order.order_id] = order
        state = OrderState(order=order, status=ORDER_STATUS_OPEN)
        self._store.write_state(state, updated_ts=now)
        return state

    async def cancel_order(self, order_id: str) -> None:
        if order_id not in self._open_orders:
            existing = self._store.get_state(order_id)
            if existing is None:
                raise UnknownOrderError(f"no such order: {order_id!r}")
            raise OrderNotCancellableError(
                f"order {order_id!r} is already {existing.status!r}, not cancellable"
            )
        order = self._open_orders.pop(order_id)
        self._store.write_state(
            OrderState(order=order, status=ORDER_STATUS_CANCELLED),
            updated_ts=datetime.now(UTC),
        )

    async def get_fills(self, order_id: str) -> list[Fill]:
        return list(self._fills_by_order.get(order_id, []))

    async def match_pending_orders(self, next_bars: dict[str, Bar]) -> list[Fill]:
        # PaperBroker fills against on_tick, not bar batches - see the
        # Broker Protocol change and docs/designs/trading-bot-first-pivot.md.
        raise NotImplementedError("PaperBroker does not support match_pending_orders")

    async def on_tick(self, tick: Tick) -> list[Fill]:
        fills = []
        for order_id, order in list(self._open_orders.items()):
            if order.symbol != tick.symbol:
                continue
            fill_price = self._slippage_model.get_fill_price(tick.price, order.side)
            fill = Fill(
                order=order,
                fill_price=fill_price,
                fill_ts=tick.ts,
                commission=self._cost_model.get_cost(order.quantity, fill_price),
            )
            fills.append(fill)
            self._fills_by_order.setdefault(order_id, []).append(fill)
            del self._open_orders[order_id]
            self._store.write_state(
                OrderState(order=order, status=ORDER_STATUS_FILLED),
                updated_ts=tick.ts,
            )
        return fills

    async def close(self) -> list[Order]:
        # A graceful shutdown, not a crash - still mark every still-open
        # order RECONCILING rather than leaving it OPEN, so a restart's
        # resume_from_store() picks it back up the same way it would after
        # an actual crash, rather than treating a clean stop specially.
        remaining = list(self._open_orders.values())
        now = datetime.now(UTC)
        for order in remaining:
            self._store.write_state(
                OrderState(order=order, status=ORDER_STATUS_RECONCILING),
                updated_ts=now,
            )
        self._open_orders = {}
        return remaining
