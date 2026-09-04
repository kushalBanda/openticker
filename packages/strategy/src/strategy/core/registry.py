from collections.abc import Callable
from typing import Any

from strategy.core.exceptions import UnknownStrategyError
from strategy.core.interfaces import Strategy

_REGISTRY: dict[str, type] = {}


def register_strategy(name: str) -> Callable[[type], type]:
    def decorator(cls: type) -> type:
        _REGISTRY[name] = cls
        return cls

    return decorator


def list_strategy_names() -> list[str]:
    return sorted(_REGISTRY)


def get_strategy_class(name: str) -> type[Strategy]:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise UnknownStrategyError(f"no strategy registered for name {name!r}") from None


class StrategyFactory:
    @staticmethod
    def create(name: str, config: dict[str, Any]) -> Strategy:
        strategy_cls = get_strategy_class(name)
        return strategy_cls(**config)
