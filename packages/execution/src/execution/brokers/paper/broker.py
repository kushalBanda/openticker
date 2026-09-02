from ingest.core.models import Bar
from strategy.core.constants import (
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_FILLED,
    ORDER_STATUS_OPEN,
    ORDER_STATUS_PARTIALLY_FILLED,
    ORDER_STATUS_REJECTED,
)
from strategy.core.models import Fill, Order, OrderState
from strategy.core.portfolio import Portfolio

from execution.core.exceptions import InvalidTransitionError
from execution.core.order_state import transition
from execution.core.risk_pipeline import RiskPipeline


def _order_id(order: Order) -> str:
    # No id field exists on Order — this deterministic signature (same
    # scheme risk_checks/duplicate_order.py uses) lets a caller derive the
    # id itself from the Order it already has, without PaperBroker handing
    # one back through a Protocol that doesn't carry it.
    return f"{order.symbol}|{order.side}|{order.quantity}|{order.placed_at_ts.isoformat()}"


class PaperBroker:
    """Fills orders against the latest known live quote instead of a
    historical bar. The same RiskPipeline that will guard LiveBroker
    later runs in front of every order here — that is the actual point
    of paper trading, proving the whole order path works before money is
    at risk. See docs/plans/execution-engine/02-architecture.md.

    Simplification, documented rather than hidden: paper fills are
    immediate and complete once a quote is known (no partial fills this
    round), so submit_order requires update_quote(symbol, price) to have
    been called for that symbol first — there is no "wait for the next
    quote" queue in this slice. A caller with no quote yet should not
    call submit_order for that symbol.
    """

    def __init__(
        self,
        risk_pipeline: RiskPipeline,
        portfolio: Portfolio,
        commission_per_share: float = 0.0,
    ) -> None:
        self._risk_pipeline = risk_pipeline
        self._portfolio = portfolio
        self._commission_per_share = commission_per_share
        self._latest_price: dict[str, float] = {}
        self._states: dict[str, OrderState] = {}
        self._fills: dict[str, list[Fill]] = {}

    def update_quote(self, symbol: str, price: float) -> None:
        self._latest_price[symbol] = price

    async def submit_order(self, order: Order) -> OrderState:
        order_id = _order_id(order)
        reference_price = self._latest_price.get(order.symbol)
        if reference_price is None:
            raise ValueError(
                f"no quote known for {order.symbol!r}; call update_quote before submit_order"
            )

        risk_result = self._risk_pipeline.check(order, self._portfolio, reference_price)
        if not risk_result.passed:
            state = OrderState(order=order, status=ORDER_STATUS_REJECTED)
            self._states[order_id] = state
            return state

        self._states[order_id] = OrderState(order=order, status=ORDER_STATUS_OPEN)

        fill = Fill(
            order=order,
            fill_price=reference_price,
            fill_ts=order.placed_at_ts,
            commission=order.quantity * self._commission_per_share,
        )
        self._portfolio.apply_fills([fill])
        self._fills.setdefault(order_id, []).append(fill)

        filled_state = OrderState(order=order, status=ORDER_STATUS_FILLED)
        self._states[order_id] = filled_state
        return filled_state

    async def cancel_order(self, order_id: str) -> None:
        state = self._states.get(order_id)
        if state is None:
            raise KeyError(f"unknown order_id {order_id!r}")
        new_status = transition(state.status, ORDER_STATUS_CANCELLED)
        self._states[order_id] = OrderState(order=state.order, status=new_status)

    async def get_fills(self, order_id: str) -> list[Fill]:
        return list(self._fills.get(order_id, []))

    async def match_pending_orders(self, next_bar: Bar) -> list[Fill]:
        # PaperBroker fills synchronously inside submit_order — paper
        # trading has no "next bar" to wait for, it has "next quote,"
        # which is now. Nothing ever accumulates here; kept only so
        # PaperBroker satisfies the same Broker Protocol as
        # BacktestBroker. See Program Design decision #4 (revised).
        return []

    async def close(self) -> list[Order]:
        # Walks every order still OPEN/PARTIALLY_FILLED and attempts to
        # cancel it rather than silently dropping it — see Program Design
        # decision #4 (revised). Today's fills are always immediate and
        # complete, so this is normally a no-op; kept for when partial
        # fills or a queued/unquoted order exist (a future slice).
        dropped: list[Order] = []
        for order_id, state in list(self._states.items()):
            if state.status in (ORDER_STATUS_OPEN, ORDER_STATUS_PARTIALLY_FILLED):
                try:
                    await self.cancel_order(order_id)
                except InvalidTransitionError:
                    dropped.append(state.order)
        return dropped
