from collections import deque

from ingest.core.models import Bar
from quant.core.series import bar_closes_to_series
from quant.core.sizer import PositionSizer
from quant.features.econometrics import volatility as realized_volatility
from quant.signals.time_series_momentum.signal import TimeSeriesMomentumSignal

from strategy.core.action import (
    ExitLongAction,
    ExitShortAction,
    ReverseToLongAction,
    ReverseToShortAction,
)
from strategy.core.interfaces import Broker
from strategy.core.portfolio import Portfolio
from strategy.core.registry import register_strategy


@register_strategy("time_series_momentum")
class TimeSeriesMomentumStrategy:
    """Moskowitz, Ooi & Pedersen (2012) time-series momentum, single
    instrument: go long when the instrument's own trailing `window`-bar
    return is positive, short when negative, flat when exactly zero.
    Position size is volatility-targeted (`quant.core.sizer.PositionSizer`),
    not a fixed share count, per the paper's construction — vol-scaling is
    not an optional extra here (unlike `sma_cross`), it is the sizing rule
    the strategy is defined by.

    Rebalances monthly, not every bar: the signal and position size are
    only recomputed the first bar seen in a new calendar month, held
    unchanged the rest of the month, matching the paper's monthly holding
    period. `window` is a bar count (e.g. ~252 for a 12-month trailing
    return on daily bars), not a calendar count, callers size it to match
    their bar interval.

    Single-instrument caveat (see docs/features/proven-strategies-single-signal.md
    candidate 1): the paper's documented Sharpe is a diversified portfolio
    across 58 instruments; a single instrument does not inherit that
    diversification benefit and should be judged on its own merits.
    """

    def __init__(self, window: int, target_risk_pct: float, vol_window: int) -> None:
        if vol_window >= window + 1:
            # Bar buffer is capped at window + 1 (the momentum signal's own
            # minimum), and a return series is one element shorter than its
            # price series — vol_window == window + 1 would need a full
            # window of vol_window valid returns out of only window
            # available, always short by one and always NaN.
            raise ValueError("vol_window must be less than window + 1")

        self._window = window
        self._signal = TimeSeriesMomentumSignal(window=window)
        self._sizer = PositionSizer(target_risk_pct=target_risk_pct)
        self._vol_window = vol_window
        self._bars: dict[str, deque[Bar]] = {}
        self._last_rebalanced_month: dict[str, tuple[int, int]] = {}

        self._exit_long = ExitLongAction()
        self._exit_short = ExitShortAction()

    async def on_bar(self, bars: dict[str, Bar], portfolio: Portfolio, broker: Broker) -> None:
        for symbol, bar in bars.items():
            await self._on_symbol_bar(symbol, bar, portfolio, broker)

    async def _on_symbol_bar(
        self, symbol: str, bar: Bar, portfolio: Portfolio, broker: Broker
    ) -> None:
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
            await ReverseToShortAction(quantity=abs(target_quantity)).execute(
                symbol, bar, portfolio, broker
            )
        else:
            await self._exit_long.execute(symbol, bar, portfolio, broker)
            await self._exit_short.execute(symbol, bar, portfolio, broker)

    def _resolve_target_quantity(
        self, symbol: str, bar: Bar, symbol_bars: list[Bar], portfolio: Portfolio, num_symbols: int
    ) -> int:
        raw = self._signal.compute(symbol_bars)
        if raw.value == 0:
            return 0
        forecast = self._signal.scale(raw)

        closes = bar_closes_to_series(symbol_bars)
        vol_pct = float(realized_volatility(closes, window=self._vol_window).iloc[-1])
        if vol_pct <= 0:
            return 0
        vol_fraction = vol_pct / 100.0

        # Mark-to-market equity, not just cash — unlike sma_cross's
        # flat-only entry, this strategy can already be holding a position
        # (long or short) when it rebalances, so cash alone understates
        # the account's true risk budget.
        position = portfolio.positions.get(symbol, 0)
        account_equity = portfolio.cash + position * bar.close

        sized = self._sizer.size(
            forecast, volatility=vol_fraction, account_equity=account_equity, price=bar.close
        )

        # PositionSizer only caps risk in one stdev move (target_risk_pct),
        # it does not cap notional — on a near-zero-volatility instrument
        # that risk-based formula divides by a tiny vol_fraction and blows
        # up into unbounded leverage. Multi-symbol universes also need each
        # instrument's budget bounded to its equal share of the book, since
        # the sizer only ever sees one instrument's risk in isolation (no
        # cross-position correlation/notional accounting, see PositionSizer's
        # own docstring). Hard-cap notional here at one no-leverage share of
        # account equity across the live universe.
        budget = account_equity / num_symbols
        max_shares = int(budget // bar.close)
        capped = max(-max_shares, min(max_shares, int(sized.size)))
        return capped
