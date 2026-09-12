"""Position sizing: volatility-targeted for single-instrument strategies,
plain capital-to-shares for pairs and momentum strategies.

Ported verbatim from quant.core.sizer.PositionSizer and
strategy.core.sizing.capital_to_quantity.
"""

from lib.math.constants import FORECAST_SCALE_MAX
from lib.math.types import Forecast, PositionSize


class PositionSizer:
    """Volatility-targeted sizing: position size scales inversely with
    the instrument's realized volatility and directly with forecast
    conviction, capped by target_risk_pct of account equity.

    Correlation adjustment against other open positions is not
    implemented here - this sizer only sees one instrument at a time.
    """

    def __init__(self, target_risk_pct: float) -> None:
        if not (0 < target_risk_pct <= 1):
            raise ValueError("target_risk_pct must be in (0, 1]")
        self._target_risk_pct = target_risk_pct

    def size(
        self, forecast: Forecast, volatility: float, account_equity: float, price: float
    ) -> PositionSize:
        if volatility <= 0:
            raise ValueError("volatility must be positive")
        if price <= 0:
            raise ValueError("price must be positive")

        conviction = forecast.scaled_value / FORECAST_SCALE_MAX
        conviction = max(-1.0, min(1.0, conviction))

        max_shares_at_full_risk = (self._target_risk_pct * account_equity) / (volatility * price)
        signed_shares = max_shares_at_full_risk * conviction

        return PositionSize(
            symbol=forecast.symbol,
            interval=forecast.interval,
            ts=forecast.ts,
            name=forecast.name,
            size=signed_shares,
            risk_pct=self._target_risk_pct * abs(conviction),
        )


def capital_to_quantity(capital: float, price: float) -> int:
    """Whole shares affordable with capital at price, floored, never
    negative. Shared by every strategy that turns a cash budget into an
    order quantity (pairs_trading, time_series_momentum).
    """
    if price <= 0:
        return 0
    return max(0, int(capital // price))
