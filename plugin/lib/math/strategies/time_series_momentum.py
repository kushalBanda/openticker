"""Moskowitz, Ooi & Pedersen (2012) time-series momentum, single
instrument: go long when the instrument's own trailing window-bar
return is positive, short when negative, flat when exactly zero.
Position size is volatility-targeted, not a fixed share count - that
sizing rule is the defining part of this strategy, not an optional
add-on. Rebalances monthly, not every bar.

Single-instrument caveat: the paper's documented Sharpe is a diversified
portfolio across 58 instruments; a single instrument does not inherit
that diversification benefit.

Ported from strategy.strategies.time_series_momentum.strategy.TimeSeriesMomentumStrategy.
"""

from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from lib.math.actions import (
    ExitLongAction,
    ExitShortAction,
    ReverseToLongAction,
    ReverseToShortAction,
)
from lib.math.broker import BacktestBroker
from lib.math.econometrics import volatility as realized_volatility
from lib.math.indicators import compute_time_series_momentum, scale_time_series_momentum
from lib.math.portfolio import Portfolio
from lib.math.series import bar_closes_to_series
from lib.math.sizing import PositionSizer, capital_to_quantity
from lib.mechanics.models import Bar


class TimeSeriesMomentumStrategy:
    def __init__(self, window: int, target_risk_pct: float, vol_window: int) -> None:
        if vol_window >= window + 1:
            raise ValueError("vol_window must be less than window + 1")

        self._window = window
        self._sizer = PositionSizer(target_risk_pct=target_risk_pct)
        self._vol_window = vol_window
        self._bars: dict[str, deque[Bar]] = {}
        self._last_rebalanced_month: dict[str, tuple[int, int]] = {}

        self._exit_long = ExitLongAction()
        self._exit_short = ExitShortAction()

    async def on_bar(self, bars: dict[str, Bar], portfolio: Portfolio, broker: BacktestBroker) -> None:
        for symbol, bar in bars.items():
            await self._on_symbol_bar(symbol, bar, portfolio, broker)

    async def _on_symbol_bar(self, symbol: str, bar: Bar, portfolio: Portfolio, broker: BacktestBroker) -> None:
        history = self._bars.setdefault(symbol, deque(maxlen=self._window + 1))
        history.append(bar)
        symbol_bars = list(history)

        if len(symbol_bars) < self._window + 1:
            return

        month_key = (bar.ts.year, bar.ts.month)
        if self._last_rebalanced_month.get(symbol) == month_key:
            return
        self._last_rebalanced_month[symbol] = month_key

        num_symbols = len(self._bars)
        target_quantity = self._resolve_target_quantity(symbol, bar, symbol_bars, portfolio, num_symbols)
        if target_quantity > 0:
            await ReverseToLongAction(quantity=target_quantity).execute(symbol, bar, portfolio, broker)
        elif target_quantity < 0:
            await ReverseToShortAction(quantity=abs(target_quantity)).execute(symbol, bar, portfolio, broker)
        else:
            await self._exit_long.execute(symbol, bar, portfolio, broker)
            await self._exit_short.execute(symbol, bar, portfolio, broker)

    def _resolve_target_quantity(
        self, symbol: str, bar: Bar, symbol_bars: list[Bar], portfolio: Portfolio, num_symbols: int
    ) -> int:
        raw = compute_time_series_momentum(symbol_bars, window=self._window)
        if raw.value == 0:
            return 0
        forecast = scale_time_series_momentum(raw)

        closes = bar_closes_to_series(symbol_bars)
        vol_pct = float(realized_volatility(closes, window=self._vol_window).iloc[-1])
        if vol_pct <= 0:
            return 0
        vol_fraction = vol_pct / 100.0

        position = portfolio.positions.get(symbol, 0)
        account_equity = portfolio.cash + position * bar.close

        sized = self._sizer.size(forecast, volatility=vol_fraction, account_equity=account_equity, price=bar.close)

        budget = account_equity / num_symbols
        max_shares = capital_to_quantity(budget, bar.close)
        capped = max(-max_shares, min(max_shares, int(sized.size)))
        return capped


OnBar = Callable[[dict[str, Bar], Portfolio, BacktestBroker], Awaitable[None]]


def make_time_series_momentum_on_bar(params: dict[str, Any]) -> OnBar:
    strategy = TimeSeriesMomentumStrategy(**params)
    return strategy.on_bar
