from collections.abc import Callable
from typing import Any

from data_engine.core.exceptions import DataUnavailableError
from data_engine.core.interfaces import MarketDataAdapter

_REGISTRY: dict[str, type] = {}


def register_adapter(name: str) -> Callable[[type], type]:
    def decorator(cls: type) -> type:
        _REGISTRY[name] = cls
        return cls

    return decorator


def get_adapter_class(name: str) -> type[MarketDataAdapter]:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise DataUnavailableError(f"no adapter registered for provider {name!r}") from None


class AdapterFactory:
    @staticmethod
    def create(provider: str, config: dict[str, Any]) -> MarketDataAdapter:
        adapter_cls = get_adapter_class(provider)
        return adapter_cls(**config)
