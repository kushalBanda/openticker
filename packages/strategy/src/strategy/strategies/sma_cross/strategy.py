from collections import deque

from ingest.core.models import Bar
from quant.core.constants import FORECAST_SCALE_MAX
from quant.core.interfaces import Forecast
from quant.core.series import bar_closes_to_series
from quant.core.sizer import PositionSizer
from quant.features.econometrics import volatility as realized_volatility
from quant.signals.sma.signal import SmaSignal

from strategy.core.action import EnterLongAction, ExitLongAction
from strategy.core.interfaces import Broker
from strategy.core.portfolio import Portfolio
from strategy.core.registry import register_strategy
from strategy.core.trigger import CrossoverTrigger


@register_strategy("sma_cross")
class SmaCrossStrategy:
    """Faber (2007) single-MA timing rule: hold shares long while price is
    above its trailing `long_window`-bar SMA, go flat (cash) when it is
    below. No short leg, unlike the old dual-MA always-in-the-market version
    this replaces — Faber's rule and its evidence (10-month SMA on the Dow
    since 1900, higher Sharpe and lower drawdown than buy-and-hold) only
    ever go long-or-flat. Price is modelled as `SmaSignal(window=1)` (an
    SMA of one bar is just that bar's close), reusing the existing SMA
    signal rather than adding a new price-only `Signal`.

    Position sizing: pass `quantity` for a fixed share count every entry
    (the old behaviour), or `target_risk_pct` + `vol_window` to size each
    entry with `quant.core.sizer.PositionSizer` instead — quantity then
    scales inversely with the stock's trailing realized volatility and is
    capped at `target_risk_pct` of account equity at entry time (entry only
    ever fires from flat, see `_entry_trigger`, so equity == cash then, no
    open-position mark-to-market to account for). The entry signal itself
    is on/off, not graded, so sizing always uses full conviction
    (`FORECAST_SCALE_MAX`) rather than a scaled forecast strength.
    Exactly one of `quantity` or `target_risk_pct` must be given.
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
            # The bar buffer is capped at long_window (see `self._bars`'
            # deque maxlen below), and a return series is one element
            # shorter than its price series (first return is undefined)
            # vol_window == long_window would need a full window of
            # long_window valid returns out of only long_window - 1
            # available, always short by one and always NaN.
            raise ValueError("vol_window must be less than long_window")

        self._long_window = long_window
        self._quantity = quantity
        self._vol_window = vol_window
        self._sizer = PositionSizer(target_risk_pct=target_risk_pct) if target_risk_pct else None
        self._bars: dict[str, deque[Bar]] = {}

        price_signal = SmaSignal(window=1)
        trend_signal = SmaSignal(window=long_window)
        self._entry_trigger = CrossoverTrigger(
            fast=price_signal, slow=trend_signal, direction="up", min_bars=long_window
        )
        self._exit_trigger = CrossoverTrigger(
            fast=price_signal, slow=trend_signal, direction="down", min_bars=long_window
        )
        self._go_flat = ExitLongAction()

    async def on_bar(self, bars: dict[str, Bar], portfolio: Portfolio, broker: Broker) -> None:
        for symbol, bar in bars.items():
            await self._on_symbol_bar(symbol, bar, portfolio, broker)

    async def _on_symbol_bar(
        self, symbol: str, bar: Bar, portfolio: Portfolio, broker: Broker
    ) -> None:
        history = self._bars.setdefault(symbol, deque(maxlen=self._long_window))
        history.append(bar)
        symbol_bars = list(history)

        # Both triggers checked every bar (not short-circuited), each keeps
        # its own fast-vs-slow baseline internally, an unchecked trigger
        # would go stale and misfire on the next flip.
        entry = self._entry_trigger.check(symbol, symbol_bars)
        exit_ = self._exit_trigger.check(symbol, symbol_bars)
        if entry:
            quantity = self._resolve_entry_quantity(symbol, bar, symbol_bars, portfolio)
            if quantity > 0:
                await EnterLongAction(quantity=quantity).execute(symbol, bar, portfolio, broker)
        elif exit_:
            await self._go_flat.execute(symbol, bar, portfolio, broker)

    def _resolve_entry_quantity(
        self, symbol: str, bar: Bar, symbol_bars: list[Bar], portfolio: Portfolio
    ) -> int:
        if self._sizer is None:
            assert self._quantity is not None  # enforced in __init__
            return self._quantity

        assert self._vol_window is not None  # enforced in __init__
        closes = bar_closes_to_series(symbol_bars)
        vol_pct = float(realized_volatility(closes, window=self._vol_window).iloc[-1])
        if vol_pct <= 0:
            return 0
        vol_fraction = vol_pct / 100.0

        forecast = Forecast(
            symbol=symbol,
            interval=bar.interval,
            ts=bar.ts,
            name="sma_cross_entry",
            scaled_value=FORECAST_SCALE_MAX,
        )
        # Entry only fires when flat (EnterLongAction no-ops otherwise), so
        # cash is the full account equity here, no open position to mark.
        position = self._sizer.size(
            forecast, volatility=vol_fraction, account_equity=portfolio.cash, price=bar.close
        )
        return int(position.size)
