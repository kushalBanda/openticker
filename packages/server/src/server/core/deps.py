import os
from functools import lru_cache
from http import HTTPStatus

import jwt as pyjwt
from dotenv import load_dotenv
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from ingest.core.engine import DataEngine
from ingest.core.interfaces import MarketDataAdapter
from ingest.core.registry import AdapterFactory
from ingest.storage.duckdb_store import DuckDBStore
from strategy.storage.equity_curve_store import EquityCurveStore
from strategy.storage.ledger_store import LedgerStore

from server.core.security import Session, decode_session_token

load_dotenv()

_bearer = HTTPBearer()


def get_jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET_KEY")
    if not secret:
        raise RuntimeError("JWT_SECRET_KEY is not set")
    return secret


@lru_cache
def get_ledger_store() -> LedgerStore:
    return LedgerStore()


@lru_cache
def get_equity_curve_store() -> EquityCurveStore:
    return EquityCurveStore()


@lru_cache
def get_duckdb_store() -> DuckDBStore:
    return DuckDBStore()


def get_session(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> Session:
    try:
        return decode_session_token(credentials.credentials, get_jwt_secret())
    except pyjwt.PyJWTError as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED,
            detail="invalid or expired session token",
        ) from exc


# Adapters carry an expensive-to-warm state (Kite's instrument master), so a
# session's adapter is built once and reused for as long as the same
# provider+credentials keep showing up, instead of reconnecting every request.
_adapter_cache: dict[tuple[str, tuple[tuple[str, str], ...]], MarketDataAdapter] = {}


async def get_adapter(session: Session = Depends(get_session)) -> MarketDataAdapter:
    key = (session["provider"], tuple(sorted(session["credentials"].items())))
    adapter = _adapter_cache.get(key)
    if adapter is None:
        adapter = AdapterFactory.create(session["provider"], session["credentials"])
        await adapter.connect()
        _adapter_cache[key] = adapter
    return adapter


async def get_data_engine(
    session: Session = Depends(get_session),
    adapter: MarketDataAdapter = Depends(get_adapter),
    store: DuckDBStore = Depends(get_duckdb_store),
) -> DataEngine:
    return DataEngine(adapters={session["provider"]: adapter}, store=store)
