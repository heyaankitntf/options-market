"""User-related Pydantic schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserResponse(BaseModel):
    id: str
    country_code: str
    phone: str
    name: str | None = None
    email: str | None = None
    is_verified: bool
    is_active: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
