import logging

from ingest.core.models import Bar

from strategy.core.interfaces import Broker, Strategy
from strategy.core.portfolio import Portfolio

logger = logging.getLogger(__name__)


class BacktestEngine:
    def __init__(self, broker: Broker, portfolio: Portfolio) -> None:
        self._broker = broker
        self._portfolio = portfolio

    async def run(self, bars: list[Bar], strategy: Strategy) -> Portfolio:
        for i, bar in enumerate(bars):
            await strategy.on_bar(bar, self._portfolio, self._broker)
            if i + 1 < len(bars):
                fills = await self._broker.match_pending_orders(bars[i + 1])
                self._portfolio.apply_fills(fills)
            self._portfolio.mark_to_market(bar)

        dropped = await self._broker.close()
        if dropped:
            logger.warning(
                "%d order(s) placed on the last bar had no next bar to fill against, dropped: %s",
                len(dropped),
                dropped,
            )
        return self._portfolio
