from strategy.core.models import Order
from strategy.core.portfolio import Portfolio

from execution.core.constants import RISK_CHECK_MAX_DAILY_LOSS
from execution.core.interfaces import RiskResult
from execution.core.registry import register_risk_check


@register_risk_check(RISK_CHECK_MAX_DAILY_LOSS)
class MaxDailyLossCheck:
    """Kill switch: blocks all new orders once the day's loss crosses
    max_daily_loss_pct of the day's starting equity.

    The "day" boundary is the NSE trading day, not UTC midnight or the
    machine's local time — a naive UTC/local reset would trip or clear
    the kill switch hours off from the actual Indian market session. To
    keep that boundary explicit and testable, this check never derives
    "a new day" from datetime.now() itself: the caller (PaperBroker, or
    a script) must call reset_for_new_trading_day() at the start of each
    NSE trading session with that session's starting equity.
    """

    def __init__(self, max_daily_loss_pct: float, starting_equity: float) -> None:
        if not (0 < max_daily_loss_pct <= 1):
            raise ValueError("max_daily_loss_pct must be in (0, 1]")
        if starting_equity <= 0:
            raise ValueError("starting_equity must be positive")
        self._max_daily_loss_pct = max_daily_loss_pct
        self._day_start_equity = starting_equity
        self._tripped = False

    def reset_for_new_trading_day(self, starting_equity: float) -> None:
        if starting_equity <= 0:
            raise ValueError("starting_equity must be positive")
        self._day_start_equity = starting_equity
        self._tripped = False

    def check(self, order: Order, portfolio: Portfolio, reference_price: float) -> RiskResult:
        # Single-instrument approximation: marks every open position at
        # reference_price (the order's symbol), same simplifying scope as
        # PositionSizer elsewhere in this platform. Fine for this round
        # (one symbol per paper run); a multi-symbol portfolio would need
        # a last-price-per-symbol map, not built here.
        current_equity = portfolio.cash + sum(
            qty * reference_price for qty in portfolio.positions.values()
        )
        loss_pct = (self._day_start_equity - current_equity) / self._day_start_equity

        if loss_pct >= self._max_daily_loss_pct:
            self._tripped = True

        if self._tripped:
            return RiskResult(
                passed=False,
                reason=(
                    f"daily loss kill switch tripped: {loss_pct:.2%} loss "
                    f"since day start, limit {self._max_daily_loss_pct:.2%}"
                ),
            )
        return RiskResult(passed=True)
