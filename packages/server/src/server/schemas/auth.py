from pydantic import BaseModel


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


class KiteLoginUrlOut(BaseModel):
    login_url: str


class GrowwLoginRequest(BaseModel):
    api_key: str
    totp_secret: str | None = None
    api_secret: str | None = None
