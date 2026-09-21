"""BROKER_REGISTRY dict + register() + get_adapter() — the one place a broker
name maps to an adapter (ADR 1 in docs/adr). Builders are resolved lazily, on each `get_adapter` call, so adapter construction (which reads
broker credentials from the environment and the stored session token from
SQLite) never happens at import time, and always sees the latest session."""

import os
from collections.abc import Callable

from openticker.adapters.brokers.zerodha.adapter import ZerodhaAdapter
from openticker.adapters.brokers.zerodha.auth import build_login_url
from openticker.ports.broker_port import BrokerPort
from openticker.storage.sqlite.credentials_repo import get_credentials


class UnknownBrokerError(Exception):
    """No adapter is registered under this broker name."""


class BrokerConfigError(Exception):
    """The broker is registered but its required configuration is missing."""


def _zerodha_credentials() -> tuple[str, str]:
    api_key = os.environ.get("KITE_API_KEY")
    api_secret = os.environ.get("KITE_API_SECRET")
    if not api_key or not api_secret:
        raise BrokerConfigError(
            "KITE_API_KEY / KITE_API_SECRET are not set — see references/kite-app-setup.md"
        )
    return api_key, api_secret


def _build_zerodha() -> BrokerPort:
    api_key, api_secret = _zerodha_credentials()
    session = get_credentials("zerodha")  # None until connect_broker has run
    return ZerodhaAdapter(
        api_key=api_key,
        api_secret=api_secret,
        access_token=session.access_token if session is not None else None,
    )


def _zerodha_login_url() -> str:
    api_key, _ = _zerodha_credentials()
    return build_login_url(api_key)


BROKER_REGISTRY: dict[str, Callable[[], BrokerPort]] = {}
_LOGIN_URL_BUILDERS: dict[str, Callable[[], str]] = {}


def register(name: str, builder: Callable[[], BrokerPort]) -> None:
    BROKER_REGISTRY[name] = builder


def register_login_url_builder(name: str, builder: Callable[[], str]) -> None:
    _LOGIN_URL_BUILDERS[name] = builder


def get_adapter(name: str) -> BrokerPort:
    builder = BROKER_REGISTRY.get(name)
    if builder is None:
        raise UnknownBrokerError(f"no broker adapter registered for {name!r}")
    return builder()


def get_login_url(name: str) -> str:
    builder = _LOGIN_URL_BUILDERS.get(name)
    if builder is None:
        raise UnknownBrokerError(f"no login-URL builder registered for {name!r}")
    return builder()


register("zerodha", _build_zerodha)
register_login_url_builder("zerodha", _zerodha_login_url)
