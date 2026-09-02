from collections.abc import Callable
from typing import Any

from execution.core.exceptions import UnknownRiskCheckError
from execution.core.interfaces import RiskCheck

_REGISTRY: dict[str, type] = {}


def register_risk_check(name: str) -> Callable[[type], type]:
    def decorator(cls: type) -> type:
        _REGISTRY[name] = cls
        return cls

    return decorator


def get_risk_check_class(name: str) -> type[RiskCheck]:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise UnknownRiskCheckError(f"no risk check registered for name {name!r}") from None


class RiskCheckFactory:
    @staticmethod
    def create(name: str, config: dict[str, Any]) -> RiskCheck:
        check_cls = get_risk_check_class(name)
        return check_cls(**config)
