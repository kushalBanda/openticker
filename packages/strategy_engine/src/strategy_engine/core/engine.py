import logging

from data_engine.core.models import Bar

from strategy_engine.core.interfaces import Broker, Strategy
from strategy_engine.core.portfolio import Portfolio

logger = logging.getLogger(__name__)


class BacktestEngine:
    def __init__(self, broker: Broker, portfolio: Portfolio) -> None:
        self._broker = broker
        self._portfolio = portfolio

    def run(self, bars: list[Bar], strategy: Strategy) -> Portfolio:
        for i, bar in enumerate(bars):
            strategy.on_bar(bar, self._portfolio, self._broker)
            if i + 1 < len(bars):
                fills = self._broker.match_pending_orders(bars[i + 1])
                self._portfolio.apply_fills(fills)
            self._portfolio.mark_to_market(bar)

        dropped = self._broker.close()
        if dropped:
            logger.warning(
                "%d order(s) placed on the last bar had no next bar to fill against, dropped: %s",
                len(dropped),
                dropped,
            )
        return self._portfolio
