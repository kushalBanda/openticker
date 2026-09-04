from collections import deque

from ingest.core.models import Bar
from quant.core.series import bar_closes_to_series
from quant.features.technicals import bollinger_bands

from strategy.core.action import (
    ExitLongAction,
    ExitShortAction,
    ReverseToLongAction,
    ReverseToShortAction,
)
from strategy.core.interfaces import Broker
from strategy.core.portfolio import Portfolio
from strategy.core.registry import register_strategy
from strategy.core.trigger import BollingerRsiEntryTrigger


@register_strategy("mean_reversion")
class MeanReversionStrategy:
    """Bollinger Band mean reversion with RSI confirmation, ported from
    docs/resources/nautilus_trader's `BBMeanReversion`
    (examples/live/architect_ax/strategies.py). Entry: price closes
    outside a band with RSI confirming the extreme (oversold -> long,
    overbought -> short), flipping straight through any opposite
    position. Exit: price reverts back to the middle band.

    Exit is checked before entry every bar and, if it fires, entry is
    skipped for that bar, matches the source's `if not self._check_exit(
    close): self._check_entry(close)`.

    The exit rule is direction-dependent (long exits above the middle,
    short exits below it), which needs the current position, the
    `Trigger` protocol (`check(symbol, bars) -> bool`) carries no
    portfolio access on purpose (see `core/trigger.py`), so unlike entry
    this is read directly here rather than wrapped in a `Trigger`.
    """

    def __init__(
        self,
        bb_window: int,
        bb_std: float,
        rsi_period: int,
        rsi_buy_threshold: float,
        rsi_sell_threshold: float,
        quantity: int,
    ) -> None:
        if rsi_buy_threshold >= rsi_sell_threshold:
            raise ValueError("rsi_buy_threshold must be less than rsi_sell_threshold")
        self._bb_window = bb_window
        self._bb_std = bb_std
        # History must cover whichever of the two needs more bars — RSI
        # needs rsi_period + 1, Bollinger needs bb_window — a deque capped
        # at bb_window alone would starve BollingerRsiEntryTrigger of the
        # one extra bar RSI needs whenever rsi_period >= bb_window.
        self._history_size = max(bb_window, rsi_period + 1)
        self._bars: dict[str, deque[Bar]] = {}

        self._oversold_trigger = BollingerRsiEntryTrigger(
            bb_window=bb_window,
            bb_std=bb_std,
            rsi_period=rsi_period,
            rsi_threshold=rsi_buy_threshold,
            direction="long",
        )
        self._overbought_trigger = BollingerRsiEntryTrigger(
            bb_window=bb_window,
            bb_std=bb_std,
            rsi_period=rsi_period,
            rsi_threshold=rsi_sell_threshold,
            direction="short",
        )
        self._go_long = ReverseToLongAction(quantity=quantity)
        self._go_short = ReverseToShortAction(quantity=quantity)
        self._exit_long = ExitLongAction()
        self._exit_short = ExitShortAction()

    async def on_bar(self, bars: dict[str, Bar], portfolio: Portfolio, broker: Broker) -> None:
        for symbol, bar in bars.items():
            await self._on_symbol_bar(symbol, bar, portfolio, broker)

    async def _on_symbol_bar(
        self, symbol: str, bar: Bar, portfolio: Portfolio, broker: Broker
    ) -> None:
        history = self._bars.setdefault(symbol, deque(maxlen=self._history_size))
        history.append(bar)
        symbol_bars = list(history)

        exited = await self._check_exit(symbol, bar, symbol_bars, portfolio, broker)
        if not exited:
            await self._check_entry(symbol, bar, symbol_bars, portfolio, broker)

    async def _check_exit(
        self, symbol: str, bar: Bar, bars: list[Bar], portfolio: Portfolio, broker: Broker
    ) -> bool:
        if len(bars) < self._bb_window:
            return False
        position = portfolio.positions.get(symbol, 0)
        if position == 0:
            return False

        middle = bollinger_bands(bar_closes_to_series(bars), window=self._bb_window)["middle"].iloc[-1]
        if position > 0 and bar.close >= middle:
            await self._exit_long.execute(symbol, bar, portfolio, broker)
            return True
        if position < 0 and bar.close <= middle:
            await self._exit_short.execute(symbol, bar, portfolio, broker)
            return True
        return False

    async def _check_entry(
        self, symbol: str, bar: Bar, bars: list[Bar], portfolio: Portfolio, broker: Broker
    ) -> None:
        # Both checked every bar (not short-circuited), each is a
        # stateless per-bar read with no baseline to go stale — unlike
        # sma_cross's CrossoverTrigger, order doesn't matter here, but
        # both are still evaluated for symmetry with that pattern.
        oversold = self._oversold_trigger.check(symbol, bars)
        overbought = self._overbought_trigger.check(symbol, bars)
        if oversold:
            await self._go_long.execute(symbol, bar, portfolio, broker)
        elif overbought:
            await self._go_short.execute(symbol, bar, portfolio, broker)
