import math

from quant.core.interfaces import Forecast, PositionSize
from quant.core.sizer import PositionSizer


class PortfolioSizer:
    """Correlation-aware capital allocation across a basket of symbols.

    Each symbol's raw size is computed independently via `PositionSizer`
    (as if uncorrelated) — an upper bound on that symbol's exposure.
    Portfolio dollar-risk is then measured as sqrt(w^T Sigma w) over those
    raw dollar exposures, where Sigma is built from each symbol's
    volatility and the pairwise correlation matrix. If that exceeds
    `target_risk_pct * account_equity`, every symbol's raw size is scaled
    down by one uniform factor to bring total portfolio risk back to the
    target — deleveraging, not per-pair reallocation.
    """

    def __init__(self, target_risk_pct: float) -> None:
        self._target_risk_pct = target_risk_pct
        self._position_sizer = PositionSizer(target_risk_pct=target_risk_pct)

    def size_all(
        self,
        forecasts: dict[str, Forecast],
        volatilities: dict[str, float],
        prices: dict[str, float],
        correlation: dict[tuple[str, str], float],
        account_equity: float,
    ) -> dict[str, PositionSize]:
        symbols = list(forecasts)
        raw_sizes = {
            symbol: self._position_sizer.size(
                forecasts[symbol], volatilities[symbol], account_equity, prices[symbol]
            )
            for symbol in symbols
        }
        dollar_exposure = {
            symbol: raw_sizes[symbol].size * prices[symbol] for symbol in symbols
        }

        portfolio_variance = sum(
            dollar_exposure[a]
            * dollar_exposure[b]
            * correlation[(a, b)]
            * volatilities[a]
            * volatilities[b]
            for a in symbols
            for b in symbols
        )
        portfolio_dollar_risk = math.sqrt(max(portfolio_variance, 0.0))
        target_dollar_risk = self._target_risk_pct * account_equity

        scale_factor = 1.0
        if portfolio_dollar_risk > target_dollar_risk and portfolio_dollar_risk > 0:
            scale_factor = target_dollar_risk / portfolio_dollar_risk

        return {
            symbol: PositionSize(
                symbol=raw_sizes[symbol].symbol,
                interval=raw_sizes[symbol].interval,
                ts=raw_sizes[symbol].ts,
                name=raw_sizes[symbol].name,
                size=raw_sizes[symbol].size * scale_factor,
                risk_pct=raw_sizes[symbol].risk_pct * scale_factor,
            )
            for symbol in symbols
        }
