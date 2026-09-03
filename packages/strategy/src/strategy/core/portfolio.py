from collections import defaultdict
from datetime import datetime

from ingest.core.models import Bar

from strategy.core.constants import ORDER_SIDE_BUY, ORDER_SIDE_SELL
from strategy.core.models import Fill


class Portfolio:
    def __init__(self, starting_cash: float) -> None:
        self._cash = starting_cash
        self._positions: dict[str, int] = defaultdict(int)
        self._equity_curve: list[tuple[datetime, float]] = []
        self._last_known_close: dict[str, float] = {}

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def positions(self) -> dict[str, int]:
        return dict(self._positions)

    @property
    def equity_curve(self) -> list[tuple[datetime, float]]:
        return list(self._equity_curve)

    def apply_fills(self, fills: list[Fill]) -> None:
        for fill in fills:
            order = fill.order
            notional = fill.fill_price * order.quantity
            if order.side == ORDER_SIDE_BUY:
                self._cash -= notional + fill.commission
                self._positions[order.symbol] += order.quantity
            elif order.side == ORDER_SIDE_SELL:
                self._cash += notional - fill.commission
                self._positions[order.symbol] -= order.quantity

    def mark_to_market(self, bars: dict[str, Bar]) -> None:
        if not bars:
            return
        for symbol, bar in bars.items():
            self._last_known_close[symbol] = bar.close
        position_value = sum(
            quantity * self._last_known_close[symbol]
            for symbol, quantity in self._positions.items()
            if symbol in self._last_known_close
        )
        ts = next(iter(bars.values())).ts
        self._equity_curve.append((ts, self._cash + position_value))
