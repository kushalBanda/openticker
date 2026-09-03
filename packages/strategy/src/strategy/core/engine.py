import logging

from ingest.core.models import Bar

from strategy.core.interfaces import Broker, Strategy
from strategy.core.portfolio import Portfolio

logger = logging.getLogger(__name__)


class BacktestEngine:
    def __init__(self, broker: Broker, portfolio: Portfolio) -> None:
        self._broker = broker
        self._portfolio = portfolio

    async def run(self, bars: dict[str, list[Bar]], strategy: Strategy) -> Portfolio:
        batches = self._build_timestep_batches(bars)
        for i, batch in enumerate(batches):
            await strategy.on_bar(batch, self._portfolio, self._broker)
            if i + 1 < len(batches):
                fills = await self._broker.match_pending_orders(batches[i + 1])
                self._portfolio.apply_fills(fills)
            self._portfolio.mark_to_market(batch)

        dropped = await self._broker.close()
        if dropped:
            logger.warning(
                "%d order(s) placed on the last bar had no next bar to fill against, dropped: %s",
                len(dropped),
                dropped,
            )
        return self._portfolio

    @staticmethod
    def _build_timestep_batches(bars: dict[str, list[Bar]]) -> list[dict[str, Bar]]:
        timestamps = sorted({bar.ts for symbol_bars in bars.values() for bar in symbol_bars})
        bars_by_symbol_ts = {
            (bar.ts, symbol): bar for symbol, symbol_bars in bars.items() for bar in symbol_bars
        }
        return [
            {
                symbol: bars_by_symbol_ts[(ts, symbol)]
                for symbol in bars
                if (ts, symbol) in bars_by_symbol_ts
            }
            for ts in timestamps
        ]
