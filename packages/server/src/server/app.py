from http import HTTPStatus

from execution.core.exceptions import ExecutionError
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from ingest.core.exceptions import (
    AuthExpiredError,
    DataUnavailableError,
    RateLimitError,
)
from strategy.core.exceptions import StrategyEngineError

from server.core.registrations import register_all
from server.routers import auth, backtest, market, portfolio


def create_app() -> FastAPI:
    register_all()
    app = FastAPI(title="Quant Platform API")

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
        # Strategy constructors (e.g. SmaCrossoverStrategy) validate their
        # own params with a plain ValueError, not a typed package
        # exception, map it to the same 422 as the typed errors above.
        return JSONResponse(
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
            content={"detail": str(exc)},
        )

    return app


app = create_app()
