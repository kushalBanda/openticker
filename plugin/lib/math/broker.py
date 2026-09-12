"""In-memory backtest broker: submits orders, fills them against the next
bar's open (adjusted by a slippage function), never same-bar.

Ported from strategy.backtest.broker.BacktestBroker, keeping only the
backtest-relevant methods. cancel_order/get_fills/on_tick are dropped:
they only ever raised NotImplementedError - dead stubs with no live/paper
broker to serve (see the design spec's "not ported" list).
"""

from collections.abc import Callable

from lib.math.constants import (
    DEFAULT_COMMISSION_PER_SHARE,
    DEFAULT_SLIPPAGE_BPS,
    ORDER_STATUS_PENDING,
)
from lib.math.cost_models import slippage_fill_price
from lib.math.models import Fill, Order, OrderState
from lib.mechanics.models import Bar


class BacktestBroker:
    def __init__(
        self,
        cost_fn: Callable[[int, float], float] | None = None,
        slippage_bps: float = DEFAULT_SLIPPAGE_BPS,
    ) -> None:
        self._cost_fn = cost_fn or (lambda quantity, price: quantity * DEFAULT_COMMISSION_PER_SHARE)
        self._slippage_bps = slippage_bps
        self._pending_orders: list[Order] = []

    async def submit_order(self, order: Order) -> OrderState:
        self._pending_orders.append(order)
        return OrderState(order=order, status=ORDER_STATUS_PENDING)

    async def match_pending_orders(self, next_bars: dict[str, Bar]) -> list[Fill]:
        fills = []
        still_pending = []
        for order in self._pending_orders:
            next_bar = next_bars.get(order.symbol)
            if next_bar is None:
                still_pending.append(order)
                continue
            fill_price = slippage_fill_price(next_bar.open, order.side, self._slippage_bps)
            fills.append(
                Fill(
                    order=order,
                    fill_price=fill_price,
                    fill_ts=next_bar.ts,
                    commission=self._cost_fn(order.quantity, fill_price),
                )
            )
        self._pending_orders = still_pending
        return fills

    async def close(self) -> list[Order]:
        dropped = self._pending_orders
        self._pending_orders = []
        return dropped
