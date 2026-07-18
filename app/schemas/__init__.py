"""Re-export all schemas for convenient imports."""

from app.schemas.market_data import (
    BarSize,
    Segment,
    TrueDataExportRequest,
    TrueDataExportResponseMeta,
)
from app.schemas.otp import DevOtpResponse, OTPRequest, OTPVerifyRequest
from app.schemas.token import TokenData, TokenResponse
from app.schemas.user import UserResponse
from pydantic import BaseModel


# Backward-compatible request bodies used by the auth routes.
class RegisterRequest(BaseModel):
    country_code: str
    phone: str
    code: str
    name: str | None = None
    email: str | None = None


class LoginRequest(BaseModel):
    country_code: str
    phone: str
    code: str


__all__ = [
    "UserResponse",
    "OTPRequest",
    "OTPVerifyRequest",
    "DevOtpResponse",
    "TokenResponse",
    "TokenData",
    "RegisterRequest",
    "LoginRequest",
    "BarSize",
    "Segment",
    "TrueDataExportRequest",
    "TrueDataExportResponseMeta",
]
