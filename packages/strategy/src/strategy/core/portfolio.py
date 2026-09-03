from collections import defaultdict
from datetime import datetime

from ingest.core.models import Bar

from strategy.core.constants import ORDER_SIDE_BUY, ORDER_SIDE_SELL
from strategy.core.ledger import LedgerEntry, TradeLedger
from strategy.core.models import Fill


class Portfolio:
    def __init__(self, starting_cash: float) -> None:
        self._cash = starting_cash
        self._positions: dict[str, int] = defaultdict(int)
        self._equity_curve: list[tuple[datetime, float]] = []
        self._last_known_close: dict[str, float] = {}
        self._cost_basis: dict[str, float] = {}
        self._ledger = TradeLedger()

    @property
    def cash(self) -> float:
        return self._cash

    @property
    def positions(self) -> dict[str, int]:
        return dict(self._positions)

    @property
    def equity_curve(self) -> list[tuple[datetime, float]]:
        return list(self._equity_curve)

    @property
    def ledger(self) -> TradeLedger:
        return self._ledger

    def apply_fills(self, fills: list[Fill]) -> None:
        for fill in fills:
            order = fill.order
            if order.side == ORDER_SIDE_BUY:
                delta = order.quantity
            elif order.side == ORDER_SIDE_SELL:
                delta = -order.quantity
            else:
                raise ValueError(f"unknown order side: {order.side}")

            symbol = order.symbol
            position_before = self._positions[symbol]
            cost_basis_before = self._cost_basis.get(symbol, 0.0)
            position_after = position_before + delta

            # Same direction as the existing position (or opening from flat):
            # growing, never realizes P&L, cost basis becomes the weighted average.
            same_direction = (position_before >= 0 and delta >= 0) or (
                position_before <= 0 and delta <= 0
            )
            if same_direction:
                realized_pnl = 0.0
                new_cost_basis = (
                    cost_basis_before * abs(position_before) + fill.fill_price * abs(delta)
                ) / abs(position_after)
            else:
                sign = 1 if position_before > 0 else -1
                if abs(delta) <= abs(position_before):
                    # Reduce or fully close, no flip through zero.
                    realized_pnl = (fill.fill_price - cost_basis_before) * abs(delta) * sign
                    new_cost_basis = cost_basis_before if position_after != 0 else 0.0
                else:
                    # Flip: close the old position, open a new one on the other side.
                    close_qty = abs(position_before)
                    realized_pnl = (fill.fill_price - cost_basis_before) * close_qty * sign
                    new_cost_basis = fill.fill_price

            notional = fill.fill_price * order.quantity
            if order.side == ORDER_SIDE_BUY:
                self._cash -= notional + fill.commission
            else:
                self._cash += notional - fill.commission
            self._positions[symbol] = position_after
            self._cost_basis[symbol] = new_cost_basis

            self._ledger.record(
                LedgerEntry(
                    symbol=symbol,
                    side=order.side,
                    quantity=order.quantity,
                    fill_price=fill.fill_price,
                    fill_ts=fill.fill_ts,
                    commission=fill.commission,
                    cost_basis_before=cost_basis_before,
                    realized_pnl=realized_pnl,
                    cash_after=self._cash,
                    position_after=position_after,
                )
            )

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
