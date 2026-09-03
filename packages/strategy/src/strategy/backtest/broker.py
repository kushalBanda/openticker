from ingest.core.models import Bar

from strategy.core.constants import (
    DEFAULT_COMMISSION_PER_SHARE,
    DEFAULT_SLIPPAGE_BPS,
    ORDER_SIDE_BUY,
    ORDER_STATUS_PENDING,
)
from strategy.core.models import Fill, Order, OrderState


class BacktestBroker:
    def __init__(
        self,
        slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
        commission_per_share: float = DEFAULT_COMMISSION_PER_SHARE,
    ) -> None:
        self._slippage_bps = slippage_bps
        self._commission_per_share = commission_per_share
        self._pending_orders: list[Order] = []

    async def submit_order(self, order: Order) -> OrderState:
        self._pending_orders.append(order)
        return OrderState(order=order, status=ORDER_STATUS_PENDING)

    async def cancel_order(self, order_id: str) -> None:
        # BacktestBroker fills against the very next bar, there is no
        # window in which a backtest order can be cancelled — no caller
        # in the backtest path needs this today.
        raise NotImplementedError("BacktestBroker does not support cancel_order")

    async def get_fills(self, order_id: str) -> list[Fill]:
        # BacktestBroker never tracked fills by order id, only by bar —
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
            fills.append(
                Fill(
                    order=order,
                    fill_price=self._apply_slippage(next_bar.open, order.side),
                    fill_ts=next_bar.ts,
                    commission=order.quantity * self._commission_per_share,
                )
            )
        self._pending_orders = still_pending
        return fills

    async def close(self) -> list[Order]:
        dropped = self._pending_orders
        self._pending_orders = []
        return dropped

    def _apply_slippage(self, price: float, side: str) -> float:
        # A buy pays a worse (higher) price, a sell receives a worse (lower)
        # price, both a realistic modeling of one-sided market impact.
        direction = 1 if side == ORDER_SIDE_BUY else -1
        return price * (1 + direction * self._slippage_bps / 10_000)
