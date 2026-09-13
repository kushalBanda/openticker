"""Deterministic sizing suggestions for scan-market: a structural stop
distance, a risk-capped position size, and a reward:risk take-profit
target. Each function returns a suggestion, not a locked decision -
scan-market's own agent can adjust any of these given its read of the
setup.
"""

from lib.math.exceptions import InsufficientDataError
from lib.mechanics.models import Bar

DEFAULT_STOP_LOOKBACK_BARS = 10
DEFAULT_REWARD_RISK_RATIO = 2.0


def suggest_stop_distance(bars: list[Bar], lookback: int = DEFAULT_STOP_LOOKBACK_BARS) -> float:
    if len(bars) < lookback:
        raise InsufficientDataError(f"suggest_stop_distance needs at least {lookback} bars, got {len(bars)}")
    recent = bars[-lookback:]
    entry_price = bars[-1].close
    structural_low = min(b.low for b in recent)
    distance = entry_price - structural_low
    if distance <= 0:
        raise ValueError(
            f"entry price {entry_price} is at or below the {lookback}-bar structural low "
            f"{structural_low}; no valid stop distance"
        )
    return distance


def suggest_position_size(capital: float, risk_per_trade_pct: float, stop_distance: float, price: float) -> int:
    if stop_distance <= 0:
        raise ValueError(f"stop_distance must be positive, got {stop_distance}")
    if price <= 0:
        raise ValueError(f"price must be positive, got {price}")
    risk_amount = capital * risk_per_trade_pct / 100
    return int(risk_amount // stop_distance)


def suggest_take_profit(entry_price: float, stop_distance: float, reward_risk_ratio: float = DEFAULT_REWARD_RISK_RATIO) -> float:
    return entry_price + stop_distance * reward_risk_ratio
