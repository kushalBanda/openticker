from collections.abc import Callable
from typing import Any

from quant.core.exceptions import UnknownSignalError
from quant.core.interfaces import Signal

_REGISTRY: dict[str, type] = {}


def register_signal(name: str) -> Callable[[type], type]:
    def decorator(cls: type) -> type:
        _REGISTRY[name] = cls
        return cls

    return decorator


def get_signal_class(name: str) -> type[Signal]:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise UnknownSignalError(f"no signal registered for name {name!r}") from None


class SignalFactory:
    @staticmethod
    def create(name: str, config: dict[str, Any]) -> Signal:
        signal_cls = get_signal_class(name)
        return signal_cls(**config)
