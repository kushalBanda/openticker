from pathlib import Path

import yaml


def load_provider_routes(path: Path) -> dict[str, str]:
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise TypeError(
            f"{path}: expected a mapping of symbol -> provider, got {type(data)}"
        )
    return {str(symbol): str(provider) for symbol, provider in data.items()}
