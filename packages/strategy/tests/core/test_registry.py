import pytest
from ingest.core.models import Bar
from strategy.core.exceptions import UnknownStrategyError
from strategy.core.interfaces import Broker
from strategy.core.portfolio import Portfolio
from strategy.core.registry import (
    StrategyFactory,
    list_strategy_names,
    register_strategy,
)


@register_strategy("fake_for_registry_test")
class FakeStrategy:
    def __init__(self, multiplier: int) -> None:
        self.multiplier = multiplier

    async def on_bar(self, bar: Bar, portfolio: Portfolio, broker: Broker) -> None:
        pass


def test_register_and_create_strategy() -> None:
    strategy = StrategyFactory.create("fake_for_registry_test", {"multiplier": 3})

    assert isinstance(strategy, FakeStrategy)
    assert strategy.multiplier == 3


def test_create_unknown_strategy_raises() -> None:
    with pytest.raises(UnknownStrategyError):
        StrategyFactory.create("does_not_exist", {})


def test_list_strategy_names_includes_registered() -> None:
    assert "fake_for_registry_test" in list_strategy_names()
