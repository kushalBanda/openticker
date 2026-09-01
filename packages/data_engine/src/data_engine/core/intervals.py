from collections.abc import Mapping

from data_engine.core.exceptions import DataUnavailableError

ProviderInterval = str | int

_INTERVAL_MAPS: dict[str, Mapping[str, ProviderInterval]] = {}


def register_interval_map(provider: str, mapping: Mapping[str, ProviderInterval]) -> None:
    _INTERVAL_MAPS[provider] = mapping


def to_provider_interval(provider: str, interval: str) -> ProviderInterval:
    try:
        provider_map = _INTERVAL_MAPS[provider]
    except KeyError:
        raise DataUnavailableError(f"no interval map registered for provider {provider!r}") from None
    try:
        return provider_map[interval]
    except KeyError:
        raise DataUnavailableError(
            f"no {provider} interval mapping for canonical interval {interval!r}"
        ) from None
