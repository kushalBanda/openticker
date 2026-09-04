import os
from hashlib import sha256
from http import HTTPStatus

import httpx
from fastapi import APIRouter, HTTPException
from growwapi.groww.exceptions import (
    GrowwAPIAuthenticationException,
    GrowwAPIAuthorisationException,
)
from ingest.core.constants import KITE_BASE_URL, PROVIDER_GROWW, PROVIDER_KITE
from ingest.core.registry import AdapterFactory

from server.core.constants import API_PREFIX_AUTH
from server.core.deps import get_jwt_secret
from server.core.security import create_session_token
from server.schemas.auth import GrowwLoginRequest, KiteLoginUrlOut, TokenOut

router = APIRouter(prefix=API_PREFIX_AUTH, tags=["auth"])


def _kite_app_credentials() -> tuple[str, str]:
    api_key = os.environ.get("KITE_API_KEY")
    api_secret = os.environ.get("KITE_API_SECRET")
    if not api_key or not api_secret:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="KITE_API_KEY / KITE_API_SECRET not configured on the server",
        )
    return api_key, api_secret


@router.get("/kite/login", response_model=KiteLoginUrlOut)
def kite_login_url() -> KiteLoginUrlOut:
    api_key, _ = _kite_app_credentials()
    return KiteLoginUrlOut(
        login_url=f"https://kite.zerodha.com/connect/login?v=3&api_key={api_key}"
    )


@router.get("/kite/callback", response_model=TokenOut)
async def kite_callback(request_token: str) -> TokenOut:
    api_key, api_secret = _kite_app_credentials()
    checksum = sha256(f"{api_key}{request_token}{api_secret}".encode()).hexdigest()

    async with httpx.AsyncClient(base_url=KITE_BASE_URL) as http:
        response = await http.post(
            "/session/token",
            data={
                "api_key": api_key,
                "request_token": request_token,
                "checksum": checksum,
            },
        )
    if response.status_code >= HTTPStatus.BAD_REQUEST:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED, detail="Kite login exchange failed"
        )

    access_token = response.json()["data"]["access_token"]
    token = create_session_token(
        PROVIDER_KITE,
        {"api_key": api_key, "access_token": access_token},
        get_jwt_secret(),
    )
    return TokenOut(access_token=token)


@router.post("/groww/login", response_model=TokenOut)
async def groww_login(request: GrowwLoginRequest) -> TokenOut:
    credentials = request.model_dump(exclude_none=True)
    adapter = AdapterFactory.create(PROVIDER_GROWW, credentials)
    try:
        await adapter.connect()
    except (GrowwAPIAuthenticationException, GrowwAPIAuthorisationException) as exc:
        raise HTTPException(
            status_code=HTTPStatus.UNAUTHORIZED, detail="Groww login failed"
        ) from exc

    token = create_session_token(PROVIDER_GROWW, credentials, get_jwt_secret())
    return TokenOut(access_token=token)
