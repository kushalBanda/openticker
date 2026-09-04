import os

from ingest.core.constants import PROVIDER_GROWW, PROVIDER_KITE

# Which env var feeds which constructor kwarg, per provider. Kept out of
# server/core/constants.py for the same reason ingest keeps interval maps
# out of its own constants.py — one dict per provider, in one file.
_ADAPTER_ENV_VARS: dict[str, dict[str, str]] = {
    PROVIDER_KITE: {
        "api_key": "KITE_API_KEY",
        "access_token": "KITE_ACCESS_TOKEN",
    },
    PROVIDER_GROWW: {
        "api_key": "GROWW_API_KEY",
        "api_secret": "GROWW_API_SECRET",
        "totp_secret": "GROWW_TOTP_SECRET",
    },
}


def load_adapter_config(provider: str) -> dict[str, str]:
    env_vars = _ADAPTER_ENV_VARS[provider]
    return {
        kwarg: value
        for kwarg, env_var in env_vars.items()
        if (value := os.environ.get(env_var)) is not None
    }
