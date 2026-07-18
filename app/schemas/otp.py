"""OTP-related Pydantic schemas."""

from datetime import datetime

from pydantic import BaseModel


class OTPRequest(BaseModel):
    """Body for requesting an OTP (registration or login)."""

    country_code: str
    phone: str


class OTPVerifyRequest(BaseModel):
    """Body for verifying an OTP."""

    country_code: str
    phone: str
    code: str


class DevOtpResponse(BaseModel):
    """DEV ONLY — the mock OTP returned so the frontend can display it."""

    phone: str
    code: str
    expires_at: datetime
    purpose: str
