"""JWT token schemas."""

from pydantic import BaseModel


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenData(BaseModel):
    """Decoded JWT payload shape."""

    sub: str | None = None
    phone: str | None = None
    country_code: str | None = None
