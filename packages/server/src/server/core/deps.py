from functools import lru_cache

from dotenv import load_dotenv
from ingest.core.engine import DataEngine
from ingest.core.interfaces import MarketDataAdapter
from ingest.core.provider_routes import load_provider_routes
from ingest.core.registry import AdapterFactory
from ingest.storage.duckdb_store import DuckDBStore
from strategy.storage.ledger_store import LedgerStore

from server.core.constants import PROVIDERS_CONFIG_PATH
from server.core.provider_credentials import load_adapter_config

load_dotenv()


@lru_cache
def get_ledger_store() -> LedgerStore:
    return LedgerStore()


@lru_cache
def get_adapters() -> dict[str, MarketDataAdapter]:
    # One adapter per distinct provider named in providers.yaml.
    providers = set(load_provider_routes(PROVIDERS_CONFIG_PATH).values())
    return {
        provider: AdapterFactory.create(provider, load_adapter_config(provider))
        for provider in providers
    }


@lru_cache
def get_data_engine() -> DataEngine:
    routes = load_provider_routes(PROVIDERS_CONFIG_PATH)
    return DataEngine(adapters=get_adapters(), store=DuckDBStore(), provider_routes=routes)
