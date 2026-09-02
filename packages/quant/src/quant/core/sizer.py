from quant.core.constants import FORECAST_SCALE_MAX
from quant.core.interfaces import Forecast, PositionSize


class PositionSizer:
    """Volatility-targeted sizing, per the HLD's default approach.

    Position size scales inversely with the instrument's realized
    volatility (so a jumpier stock gets a smaller position for the same
    dollar risk) and directly with forecast conviction (a forecast near
    the +/-20 extreme sizes up towards the full risk budget, a forecast
    near 0 sizes down towards nothing). Capped by `target_risk_pct` of
    account equity — the maximum this position risks in one stdev move.

    Correlation adjustment against other open positions (HLD's third
    sizing factor) is not implemented here — this sizer only sees one
    instrument at a time. That's a combiner-level concern once more than
    one position can be open simultaneously, out of scope for this slice.
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

        max_shares_at_full_risk = (self._target_risk_pct * account_equity) / (
            volatility * price
        )
        signed_shares = max_shares_at_full_risk * conviction

        return PositionSize(
            symbol=forecast.symbol,
            interval=forecast.interval,
            ts=forecast.ts,
            name=forecast.name,
            size=signed_shares,
            risk_pct=self._target_risk_pct * abs(conviction),
        )
