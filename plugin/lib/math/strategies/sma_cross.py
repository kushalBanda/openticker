"""Faber (2007) single-MA timing rule: hold shares long while price is
above its trailing long_window-bar SMA, go flat (cash) when it is below.

Ported from strategy.strategies.sma_cross.strategy.SmaCrossStrategy,
dropping @register_strategy - make_sma_cross_on_bar is the dispatch
entry point run_backtest.py's script uses instead.
"""

from collections import deque
from collections.abc import Awaitable, Callable
from typing import Any

from lib.math.actions import EnterLongAction, ExitLongAction
from lib.math.broker import BacktestBroker
from lib.math.constants import FORECAST_SCALE_MAX
from lib.math.econometrics import volatility as realized_volatility
from lib.math.indicators import compute_sma
from lib.math.portfolio import Portfolio
from lib.math.series import bar_closes_to_series
from lib.math.sizing import PositionSizer
from lib.math.triggers import CrossoverTrigger
from lib.math.types import Forecast
from lib.mechanics.models import Bar


class SmaCrossStrategy:
    """Position sizing: pass quantity for a fixed share count every entry,
    or target_risk_pct + vol_window to size each entry with PositionSizer
    instead. Exactly one of quantity or target_risk_pct must be given.
    """

    def __init__(
        self,
        long_window: int,
        quantity: int | None = None,
        target_risk_pct: float | None = None,
        vol_window: int | None = None,
    ) -> None:
        if (quantity is None) == (target_risk_pct is None):
            raise ValueError("pass exactly one of quantity or target_risk_pct")
        if target_risk_pct is not None and vol_window is None:
            raise ValueError("vol_window is required when target_risk_pct is given")
        if vol_window is not None and vol_window >= long_window:
            raise ValueError("vol_window must be less than long_window")

        self._long_window = long_window
        self._quantity = quantity
        self._vol_window = vol_window
        self._sizer = PositionSizer(target_risk_pct=target_risk_pct) if target_risk_pct else None
        self._bars: dict[str, deque[Bar]] = {}

        def price_signal(bars: list[Bar]) -> Any:
            return compute_sma(bars, window=1)

        def trend_signal(bars: list[Bar]) -> Any:
            return compute_sma(bars, window=long_window)

        self._entry_trigger = CrossoverTrigger(fast=price_signal, slow=trend_signal, direction="up", min_bars=long_window)
        self._exit_trigger = CrossoverTrigger(fast=price_signal, slow=trend_signal, direction="down", min_bars=long_window)
        self._go_flat = ExitLongAction()

    async def on_bar(self, bars: dict[str, Bar], portfolio: Portfolio, broker: BacktestBroker) -> None:
        for symbol, bar in bars.items():
            await self._on_symbol_bar(symbol, bar, portfolio, broker)

    async def _on_symbol_bar(self, symbol: str, bar: Bar, portfolio: Portfolio, broker: BacktestBroker) -> None:
        history = self._bars.setdefault(symbol, deque(maxlen=self._long_window))
        history.append(bar)
        symbol_bars = list(history)

        entry = self._entry_trigger.check(symbol, symbol_bars)
        exit_ = self._exit_trigger.check(symbol, symbol_bars)
        if entry:
            quantity = self._resolve_entry_quantity(symbol, bar, symbol_bars, portfolio)
            if quantity > 0:
                await EnterLongAction(quantity=quantity).execute(symbol, bar, portfolio, broker)
        elif exit_:
            await self._go_flat.execute(symbol, bar, portfolio, broker)

    def _resolve_entry_quantity(self, symbol: str, bar: Bar, symbol_bars: list[Bar], portfolio: Portfolio) -> int:
        if self._sizer is None:
            assert self._quantity is not None
            return self._quantity

        assert self._vol_window is not None
        closes = bar_closes_to_series(symbol_bars)
        vol_pct = float(realized_volatility(closes, window=self._vol_window).iloc[-1])
        if vol_pct <= 0:
            return 0
        vol_fraction = vol_pct / 100.0

        forecast = Forecast(symbol=symbol, interval=bar.interval, ts=bar.ts, name="sma_cross_entry", scaled_value=FORECAST_SCALE_MAX)
        position = self._sizer.size(forecast, volatility=vol_fraction, account_equity=portfolio.cash, price=bar.close)
        return int(position.size)


OnBar = Callable[[dict[str, Bar], Portfolio, BacktestBroker], Awaitable[None]]


def make_sma_cross_on_bar(params: dict[str, Any]) -> OnBar:
    strategy = SmaCrossStrategy(**params)
    return strategy.on_bar
