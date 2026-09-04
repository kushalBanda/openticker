import time
from typing import TypedDict

import jwt

from server.core.constants import JWT_ALGORITHM, JWT_EXPIRY_SECONDS


class Session(TypedDict):
    provider: str
    credentials: dict[str, str]


def create_session_token(provider: str, credentials: dict[str, str], secret: str) -> str:
    payload = {
        "provider": provider,
        "credentials": credentials,
        "exp": int(time.time()) + JWT_EXPIRY_SECONDS,
    }
    return jwt.encode(payload, secret, algorithm=JWT_ALGORITHM)


def decode_session_token(token: str, secret: str) -> Session:
    payload = jwt.decode(token, secret, algorithms=[JWT_ALGORITHM])
    return Session(provider=payload["provider"], credentials=payload["credentials"])
