"""Re-export all models so `from app.models import User, OTP` works."""

from app.models.otp import OTP
from app.models.user import User

__all__ = ["User", "OTP"]
