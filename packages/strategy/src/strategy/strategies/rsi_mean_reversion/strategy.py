from collections import deque

from ingest.core.models import Bar
from quant.core.exceptions import InsufficientDataError
from quant.signals.rsi.signal import RsiSignal

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
        self._bars: deque[Bar] = deque(maxlen=period + 1)
        self._signal = RsiSignal(period=period)

    async def on_bar(self, bar: Bar, portfolio: Portfolio, broker: Broker) -> None:
        self._bars.append(bar)
        try:
            raw = self._signal.compute(list(self._bars))
        except InsufficientDataError:
            return
        # Decision still reads the raw RSI value (0..100), not the scaled
        # Forecast, so backtest output stays bit-identical to the pre-signal
        # implementation. See docs/plans/quant-research-layer/03-program-design.md
        # least-confident decision #2.
        self._signal.scale(raw)

        position = portfolio.positions.get(bar.symbol, 0)

        if raw.value < self._oversold and position == 0:
            await broker.submit_order(
                Order(
                    symbol=bar.symbol,
                    side=ORDER_SIDE_BUY,
                    quantity=self._quantity,
                    order_type=ORDER_TYPE_MARKET,
                    placed_at_ts=bar.ts,
                )
            )
        elif raw.value > self._overbought and position > 0:
            await broker.submit_order(
                Order(
                    symbol=bar.symbol,
                    side=ORDER_SIDE_SELL,
                    quantity=position,
                    order_type=ORDER_TYPE_MARKET,
                    placed_at_ts=bar.ts,
                )
            )
