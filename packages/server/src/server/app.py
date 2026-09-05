import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from http import HTTPStatus

import httpx
from execution.core.exceptions import ExecutionError
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from ingest.core.constants import KNOWN_INDICES, SOURCE_NSE_CSV
from ingest.core.exceptions import (
    AuthExpiredError,
    DataUnavailableError,
    RateLimitError,
)
from ingest.core.index_constituents import fetch_index_constituents
from ingest.core.models import IndexConstituent
from strategy.core.exceptions import StrategyEngineError

from server.core.deps import get_duckdb_store
from server.core.registrations import register_all
from server.routers import auth, backtest, market, portfolio

logger = logging.getLogger(__name__)


async def _load_index_constituents(app: FastAPI) -> None:
    # Best-effort warm cache: fetches NSE's live constituent CSVs on boot
    # so the strategy universe is populated without a manual POST first.
    # NSE being unreachable must never block server startup, so failures
    # are logged and skipped per index.
    # Resolves the store through dependency_overrides (if any) rather than
    # calling get_duckdb_store() directly, so tests that override it with
    # a tmp_path-backed store aren't bypassed by this startup hook.
    store_provider = app.dependency_overrides.get(get_duckdb_store, get_duckdb_store)
    store = store_provider()
    year = datetime.now(UTC).year
    for index_name in KNOWN_INDICES:
        try:
            symbols = await fetch_index_constituents(index_name)
        except (httpx.HTTPError, ValueError):
            logger.warning(
                "startup index-constituents fetch failed for %s", index_name
            )
            continue
        store.write_index_constituents(
            [
                IndexConstituent(
                    index_name=index_name,
                    symbol=symbol,
                    year=year,
                    source=SOURCE_NSE_CSV,
                )
                for symbol in symbols
            ]
        )


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    await _load_index_constituents(app)
    yield


def create_app() -> FastAPI:
    register_all()
    app = FastAPI(title="Quant Platform API", lifespan=_lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router)
    app.include_router(backtest.router)
    app.include_router(backtest.action_router)
    app.include_router(portfolio.router)
    app.include_router(market.router)

    @app.exception_handler(StrategyEngineError)
    async def _strategy_error_handler(
        _request: Request, exc: StrategyEngineError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            content={"detail": str(exc)},
        )

    @app.exception_handler(ExecutionError)
    async def _execution_error_handler(
        _request: Request, exc: ExecutionError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            content={"detail": str(exc)},
        )

    @app.exception_handler(DataUnavailableError)
    async def _data_unavailable_handler(
        _request: Request, exc: DataUnavailableError
    ) -> JSONResponse:
        # Symbol not in the logged-in provider's instrument master, or not
        # yet cached and not fetchable, "no route to fetch this symbol".
        return JSONResponse(
            status_code=HTTPStatus.NOT_FOUND, content={"detail": str(exc)}
        )

    @app.exception_handler(AuthExpiredError)
    async def _auth_expired_handler(
        _request: Request, exc: AuthExpiredError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=HTTPStatus.UNAUTHORIZED, content={"detail": str(exc)}
        )

    @app.exception_handler(RateLimitError)
    async def _rate_limit_handler(
        _request: Request, exc: RateLimitError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=HTTPStatus.TOO_MANY_REQUESTS, content={"detail": str(exc)}
        )

    @app.exception_handler(ValueError)
    async def _value_error_handler(_request: Request, exc: ValueError) -> JSONResponse:
        # Strategy constructors (e.g. SmaCrossStrategy) validate their
        # own params with a plain ValueError, not a typed package
        # exception, map it to the same 422 as the typed errors above.
        return JSONResponse(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            content={"detail": str(exc)},
        )

    return app


app = create_app()
