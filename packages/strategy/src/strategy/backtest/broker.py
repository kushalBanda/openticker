from ingest.core.models import Bar, Tick

from strategy.core.constants import (
    DEFAULT_COMMISSION_PER_SHARE,
    DEFAULT_SLIPPAGE_BPS,
    ORDER_STATUS_PENDING,
)
from strategy.core.cost_model import (
    BpsSlippageModel,
    PerShareFeeModel,
    SlippageModel,
    TransactionCostModel,
)
from strategy.core.models import Fill, Order, OrderState


class BacktestBroker:
    def __init__(
        self,
        cost_model: TransactionCostModel | None = None,
        slippage_model: SlippageModel | None = None,
    ) -> None:
        # Built fresh per instance, not a shared module-level default: both
        # concrete models are stateless today, but a shared default instance
        # would silently become a footgun the day either grows mutable state.
        self._cost_model = cost_model or PerShareFeeModel(DEFAULT_COMMISSION_PER_SHARE)
        self._slippage_model = slippage_model or BpsSlippageModel(DEFAULT_SLIPPAGE_BPS)
        self._pending_orders: list[Order] = []

    async def submit_order(self, order: Order) -> OrderState:
        self._pending_orders.append(order)
        return OrderState(order=order, status=ORDER_STATUS_PENDING)

    async def cancel_order(self, order_id: str) -> None:
        # BacktestBroker fills against the very next bar, there is no
        # window in which a backtest order can be cancelled - no caller
        # in the backtest path needs this today.
        raise NotImplementedError("BacktestBroker does not support cancel_order")

    async def get_fills(self, order_id: str) -> list[Fill]:
        # BacktestBroker never tracked fills by order id, only by bar -
        # fills are consumed from match_pending_orders as they happen.
        raise NotImplementedError("BacktestBroker does not support get_fills")

    async def match_pending_orders(self, next_bars: dict[str, Bar]) -> list[Fill]:
        fills = []
        still_pending = []
        for order in self._pending_orders:
            next_bar = next_bars.get(order.symbol)
            if next_bar is None:
                still_pending.append(order)
                continue
            fill_price = self._slippage_model.get_fill_price(next_bar.open, order.side)
            fills.append(
                Fill(
                    order=order,
                    fill_price=fill_price,
                    fill_ts=next_bar.ts,
                    commission=self._cost_model.get_cost(order.quantity, fill_price),
                )
            )
        self._pending_orders = still_pending
        return fills

    async def on_tick(self, tick: Tick) -> list[Fill]:
        # BacktestBroker replays historical bars via match_pending_orders,
        # it has no live tick stream to fill against.
        raise NotImplementedError("BacktestBroker does not support on_tick")

    async def close(self) -> list[Order]:
        dropped = self._pending_orders
        self._pending_orders = []
        return dropped
