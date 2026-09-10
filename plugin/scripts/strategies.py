"""Registers packages/strategy's strategies for StrategyFactory.create(...).

`strategy.strategies` is a deliberately empty __init__.py - a strategy
only self-registers (via @register_strategy) when its concrete module is
actually imported. Same reason adapters.py exists for ingest's adapters.
"""

from importlib import import_module

_STRATEGY_MODULES = (
    "strategy.strategies.sma_cross.strategy",
    "strategy.strategies.buy_and_hold.strategy",
    "strategy.strategies.mean_reversion.strategy",
    "strategy.strategies.pairs_trading.strategy",
    "strategy.strategies.time_series_momentum.strategy",
)

_registered = False


def ensure_strategies_registered() -> None:
    global _registered
    if _registered:
        return
    for module in _STRATEGY_MODULES:
        import_module(module)
    _registered = True
