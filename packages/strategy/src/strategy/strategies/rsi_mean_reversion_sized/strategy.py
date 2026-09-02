from collections import deque

from ingest.core.models import Bar
from quant.core.exceptions import InsufficientDataError
from quant.core.sizer import PositionSizer
from quant.features.volatility import realized_volatility
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


@register_strategy("rsi_mean_reversion_sized")
class RsiMeanReversionSizedStrategy:
    """Same entry/exit rule as RsiMeanReversionStrategy (buy oversold, sell
    overbought), but the BUY quantity comes from PositionSizer's
    volatility-targeted sizing instead of a fixed number of shares. SELL
    still exits the full existing position — sizing only ever governs how
    much to enter with, never a partial exit.

    Direction still comes entirely from the oversold/overbought threshold
    crossing, exactly as before. The RSI forecast's sign is contrarian for
    a mean-reversion rule (low RSI -> negative forecast, which is exactly
    when we want to buy) so only the forecast's magnitude (abs of the
    sizer's output) is used for sizing — the sign is never consulted for
    direction here.
    """

    def __init__(
        self, period: int, oversold: float, overbought: float, target_risk_pct: float
    ) -> None:
        if not (0 < oversold < overbought < 100):
            raise ValueError("require 0 < oversold < overbought < 100")
        self._period = period
        self._oversold = oversold
        self._overbought = overbought
        self._bars: deque[Bar] = deque(maxlen=period + 1)
        self._signal = RsiSignal(period=period)
        self._sizer = PositionSizer(target_risk_pct=target_risk_pct)

    async def on_bar(self, bar: Bar, portfolio: Portfolio, broker: Broker) -> None:
        self._bars.append(bar)
        try:
            raw = self._signal.compute(list(self._bars))
        except InsufficientDataError:
            return

        position = portfolio.positions.get(bar.symbol, 0)

        if raw.value < self._oversold and position == 0:
            closes = [b.close for b in self._bars]
            try:
                volatility = realized_volatility(closes)
            except InsufficientDataError:
                return
            if volatility <= 0:
                return

            forecast = self._signal.scale(raw)
            account_equity = portfolio.cash + position * bar.close
            sized = self._sizer.size(
                forecast,
                volatility=volatility,
                account_equity=account_equity,
                price=bar.close,
            )
            quantity = round(abs(sized.size))
            if quantity < 1:
                return

            await broker.submit_order(
                Order(
                    symbol=bar.symbol,
                    side=ORDER_SIDE_BUY,
                    quantity=quantity,
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
