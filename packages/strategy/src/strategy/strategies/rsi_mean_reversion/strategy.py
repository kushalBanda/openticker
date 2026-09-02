from collections import deque

from ingest.core.models import Bar

from strategy.core.constants import (
    ORDER_SIDE_BUY,
    ORDER_SIDE_SELL,
    ORDER_TYPE_MARKET,
)
from strategy.core.interfaces import Broker
from strategy.core.models import Order
from strategy.core.portfolio import Portfolio
from strategy.core.registry import register_strategy


@register_strategy("rsi_mean_reversion")
class RsiMeanReversionStrategy:
    def __init__(
        self, period: int, oversold: float, overbought: float, quantity: int
    ) -> None:
        if not (0 < oversold < overbought < 100):
            raise ValueError("require 0 < oversold < overbought < 100")
        self._period = period
        self._oversold = oversold
        self._overbought = overbought
        self._quantity = quantity
        self._closes: deque[float] = deque(maxlen=period + 1)

    def on_bar(self, bar: Bar, portfolio: Portfolio, broker: Broker) -> None:
        self._closes.append(bar.close)
        if len(self._closes) < self._period + 1:
            return

        rsi = self._compute_rsi()
        position = portfolio.positions.get(bar.symbol, 0)

        if rsi < self._oversold and position == 0:
            broker.submit_order(
                Order(
                    symbol=bar.symbol,
                    side=ORDER_SIDE_BUY,
                    quantity=self._quantity,
                    order_type=ORDER_TYPE_MARKET,
                    placed_at_ts=bar.ts,
                )
            )
        elif rsi > self._overbought and position > 0:
            broker.submit_order(
                Order(
                    symbol=bar.symbol,
                    side=ORDER_SIDE_SELL,
                    quantity=position,
                    order_type=ORDER_TYPE_MARKET,
                    placed_at_ts=bar.ts,
                )
            )

    def _compute_rsi(self) -> float:
        closes = list(self._closes)
        gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, len(closes))]
        losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, len(closes))]
        avg_gain = sum(gains) / self._period
        avg_loss = sum(losses) / self._period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))
