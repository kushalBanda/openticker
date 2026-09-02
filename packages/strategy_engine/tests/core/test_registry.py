import pytest
from data_engine.core.models import Bar
from strategy_engine.core.exceptions import UnknownStrategyError
from strategy_engine.core.interfaces import Broker
from strategy_engine.core.portfolio import Portfolio
from strategy_engine.core.registry import StrategyFactory, register_strategy


@register_strategy("fake_for_registry_test")
class FakeStrategy:
    def __init__(self, multiplier: int) -> None:
        self.multiplier = multiplier

    def on_bar(self, bar: Bar, portfolio: Portfolio, broker: Broker) -> None:
        pass


def test_register_and_create_strategy() -> None:
    strategy = StrategyFactory.create("fake_for_registry_test", {"multiplier": 3})

    assert isinstance(strategy, FakeStrategy)
    assert strategy.multiplier == 3


def test_create_unknown_strategy_raises() -> None:
    with pytest.raises(UnknownStrategyError):
        StrategyFactory.create("does_not_exist", {})
