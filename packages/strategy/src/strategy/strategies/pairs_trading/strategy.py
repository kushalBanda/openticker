import calendar
from collections import deque
from dataclasses import dataclass
from datetime import date

from ingest.core.models import Bar
from quant.core.exceptions import InsufficientDataError
from quant.core.series import bar_closes_to_series
from quant.features.pairs import (
    Pair,
    SpreadBaseline,
    select_pairs,
    spread_baseline,
    spread_value,
    zscore,
)

from strategy.core.action import (
    ExitLongAction,
    ExitShortAction,
    ReverseToLongAction,
    ReverseToShortAction,
)
from strategy.core.interfaces import Broker
from strategy.core.portfolio import Portfolio
from strategy.core.registry import register_strategy


def _add_months(day: date, months: int) -> date:
    total = day.month - 1 + months
    year = day.year + total // 12
    month = total % 12 + 1
    last_day_of_month = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last_day_of_month))


@dataclass(frozen=True)
class SelectedPair:
    pair: Pair
    baseline: SpreadBaseline


@dataclass(frozen=True)
class OpenPairPosition:
    long_symbol: str
    short_symbol: str
    entry_z_sign: int


@register_strategy("pairs_trading")
class PairsTradingStrategy:
    """Gatev, Goetzmann & Rouwenhorst pairs trading: every `trading_months`,
    force-unwinds any open pair positions, re-ranks every symbol pair in the
    universe by sum-of-squared-deviation over the trailing `formation_months`
    (`quant.features.pairs.select_pairs`), keeps the top `top_n_pairs`, and
    freezes each kept pair's spread mean/std over that same window
    (`spread_baseline`). During the following trading window, each selected
    pair's live spread is z-scored against its frozen baseline (never
    re-anchored mid-period): flat and `|z| > entry_z` opens the pair
    (short the rich leg, long the cheap leg, equal-weight dollar-neutral
    sizing across the top `top_n_pairs` slots); open and the z-score's sign
    has flipped since entry (crossed back through the frozen mean) closes
    both legs.
    """

    def __init__(
        self,
        formation_months: int,
        trading_months: int,
        top_n_pairs: int,
        entry_z: float,
    ) -> None:
        if formation_months < 1:
            raise ValueError("formation_months must be at least 1")
        if trading_months < 1:
            raise ValueError("trading_months must be at least 1")
        if top_n_pairs < 1:
            raise ValueError("top_n_pairs must be at least 1")
        if entry_z <= 0:
            raise ValueError("entry_z must be positive")

        self._formation_months = formation_months
        self._trading_months = trading_months
        self._top_n_pairs = top_n_pairs
        self._entry_z = entry_z

        self._history: dict[str, deque[Bar]] = {}
        self._next_reformation_date: date | None = None
        self._selected: list[SelectedPair] = []
        self._open: dict[tuple[str, str], OpenPairPosition] = {}
        self._capital_per_pair = 0.0

    async def on_bar(self, bars: dict[str, Bar], portfolio: Portfolio, broker: Broker) -> None:
        self._append_and_trim_history(bars)
        today = next(iter(bars.values())).ts.date()

        if self._next_reformation_date is None:
            self._next_reformation_date = _add_months(today, self._formation_months)

        if self._reformation_due(today):
            await self._unwind_all(bars, portfolio, broker)
            self._reform(portfolio)
            self._next_reformation_date = _add_months(self._next_reformation_date, self._trading_months)

        for selected in list(self._selected):
            await self._check_pair(selected, bars, portfolio, broker)

    def _append_and_trim_history(self, bars: dict[str, Bar]) -> None:
        for symbol, bar in bars.items():
            history = self._history.setdefault(symbol, deque())
            history.append(bar)
            cutoff = _add_months(bar.ts.date(), -self._formation_months)
            while history and history[0].ts.date() < cutoff:
                history.popleft()

    def _reformation_due(self, today: date) -> bool:
        return self._next_reformation_date is not None and today >= self._next_reformation_date

    async def _unwind_all(self, bars: dict[str, Bar], portfolio: Portfolio, broker: Broker) -> None:
        for key, position in list(self._open.items()):
            long_bar = bars.get(position.long_symbol)
            short_bar = bars.get(position.short_symbol)
            if long_bar is not None:
                await ExitLongAction().execute(position.long_symbol, long_bar, portfolio, broker)
            if short_bar is not None:
                await ExitShortAction().execute(position.short_symbol, short_bar, portfolio, broker)
            del self._open[key]

    def _reform(self, portfolio: Portfolio) -> None:
        self._selected = []
        self._capital_per_pair = portfolio.cash / self._top_n_pairs

        formation_closes = {
            symbol: bar_closes_to_series(list(history))
            for symbol, history in self._history.items()
            if len(history) >= 2
        }
        try:
            pairs = select_pairs(formation_closes, self._top_n_pairs)
        except InsufficientDataError:
            return

        for pair in pairs:
            closes_a = bar_closes_to_series(list(self._history[pair.symbol_a]))
            closes_b = bar_closes_to_series(list(self._history[pair.symbol_b]))
            try:
                baseline = spread_baseline(closes_a, closes_b, pair.anchor_a, pair.anchor_b)
            except InsufficientDataError:
                continue
            self._selected.append(SelectedPair(pair=pair, baseline=baseline))

    async def _check_pair(
        self, selected: SelectedPair, bars: dict[str, Bar], portfolio: Portfolio, broker: Broker
    ) -> None:
        pair = selected.pair
        bar_a = bars.get(pair.symbol_a)
        bar_b = bars.get(pair.symbol_b)
        if bar_a is None or bar_b is None:
            return

        key = (pair.symbol_a, pair.symbol_b)
        value = spread_value(bar_a.close, bar_b.close, pair.anchor_a, pair.anchor_b)
        z = zscore(value, selected.baseline)

        open_position = self._open.get(key)
        if open_position is None:
            await self._maybe_enter(key, pair, z, bar_a, bar_b, portfolio, broker)
        else:
            await self._maybe_exit(key, open_position, z, bars, portfolio, broker)

    async def _maybe_enter(
        self,
        key: tuple[str, str],
        pair: Pair,
        z: float,
        bar_a: Bar,
        bar_b: Bar,
        portfolio: Portfolio,
        broker: Broker,
    ) -> None:
        if abs(z) <= self._entry_z:
            return

        if z > 0:
            short_symbol, short_bar = pair.symbol_a, bar_a
            long_symbol, long_bar = pair.symbol_b, bar_b
        else:
            short_symbol, short_bar = pair.symbol_b, bar_b
            long_symbol, long_bar = pair.symbol_a, bar_a

        quantity_long = int(self._capital_per_pair // long_bar.close)
        quantity_short = int(self._capital_per_pair // short_bar.close)
        if quantity_long <= 0 or quantity_short <= 0:
            return

        await ReverseToLongAction(quantity_long).execute(long_symbol, long_bar, portfolio, broker)
        await ReverseToShortAction(quantity_short).execute(short_symbol, short_bar, portfolio, broker)

        self._open[key] = OpenPairPosition(
            long_symbol=long_symbol,
            short_symbol=short_symbol,
            entry_z_sign=1 if z > 0 else -1,
        )

    async def _maybe_exit(
        self,
        key: tuple[str, str],
        open_position: OpenPairPosition,
        z: float,
        bars: dict[str, Bar],
        portfolio: Portfolio,
        broker: Broker,
    ) -> None:
        current_sign = 1 if z > 0 else -1
        if current_sign == open_position.entry_z_sign:
            return

        long_bar = bars.get(open_position.long_symbol)
        short_bar = bars.get(open_position.short_symbol)
        if long_bar is not None:
            await ExitLongAction().execute(open_position.long_symbol, long_bar, portfolio, broker)
        if short_bar is not None:
            await ExitShortAction().execute(open_position.short_symbol, short_bar, portfolio, broker)
        del self._open[key]
