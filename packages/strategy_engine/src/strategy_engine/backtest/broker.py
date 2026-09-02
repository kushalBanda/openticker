from data_engine.core.models import Bar

from strategy_engine.core.constants import (
    DEFAULT_COMMISSION_PER_SHARE,
    DEFAULT_SLIPPAGE_BPS,
)
from strategy_engine.core.models import Fill, Order


class BacktestBroker:
    def __init__(
        self,
        slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
        commission_per_share: float = DEFAULT_COMMISSION_PER_SHARE,
    ) -> None:
        self._slippage_bps = slippage_bps
        self._commission_per_share = commission_per_share
        self._pending_orders: list[Order] = []

    def submit_order(self, order: Order) -> None:
        self._pending_orders.append(order)

    def match_pending_orders(self, next_bar: Bar) -> list[Fill]:
        fills = [
            Fill(
                order=order,
                fill_price=self._apply_slippage(next_bar.open),
                fill_ts=next_bar.ts,
                commission=order.quantity * self._commission_per_share,
            )
            for order in self._pending_orders
        ]
        self._pending_orders = []
        return fills

    def _apply_slippage(self, price: float) -> float:
        return price * (1 + self._slippage_bps / 10_000)
