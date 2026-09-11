from engine.core.strategies import ensure_strategies_registered
from strategy.core.registry import get_strategy_class


def test_ensure_strategies_registered_registers_sma_cross() -> None:
    ensure_strategies_registered()
    assert get_strategy_class("sma_cross") is not None


def test_ensure_strategies_registered_is_idempotent() -> None:
    ensure_strategies_registered()
    ensure_strategies_registered()
    assert get_strategy_class("sma_cross") is not None
