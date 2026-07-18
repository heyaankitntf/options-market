"""OTP generation + verification logic."""

import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.otp import OTP
from app.models.user import User


def _utcnow_naive() -> datetime:
    """Current UTC time as a naive datetime (matches SQLite's storage)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def generate_otp() -> str:
    """Generate a cryptographically random numeric OTP."""
    return "".join(
        [str(secrets.randbelow(10)) for _ in range(settings.OTP_LENGTH)]
    )


def create_otp(
    db: Session, country_code: str, phone: str, purpose: str = "login"
) -> OTP:
    """Create + persist a new OTP for the given phone."""
    otp_code = generate_otp()
    expires_at = _utcnow_naive() + timedelta(minutes=settings.OTP_EXPIRE_MINUTES)

    otp = OTP(
        country_code=country_code,
        phone=phone,
        code=otp_code,
        expires_at=expires_at,
        purpose=purpose,
    )
    db.add(otp)
    db.commit()
    db.refresh(otp)
    return otp


def verify_otp(
    db: Session, country_code: str, phone: str, code: str
) -> tuple[bool, str]:
    """Verify the latest unused OTP for a phone. Marks it used on success."""
    otp = (
        db.query(OTP)
        .filter(
            OTP.country_code == country_code,
            OTP.phone == phone,
            OTP.used == False,  # noqa: E712
        )
        .order_by(OTP.created_at.desc())
        .first()
    )

    if not otp:
        return False, "No OTP found"

    if otp.expires_at < _utcnow_naive():
        return False, "OTP expired"

    if otp.code != code:
        return False, "Invalid OTP"

    otp.used = True
    db.commit()

    # If the user exists but isn't verified yet, verify them now.
    user = db.query(User).filter(User.phone == phone).first()
    if user and not user.is_verified:
        user.is_verified = True
        db.commit()

    return True, "OTP verified"


def get_valid_otp(db: Session, country_code: str, phone: str) -> OTP | None:
    """Return the latest valid (unused, unexpired) OTP, if any."""
    return (
        db.query(OTP)
        .filter(
            OTP.country_code == country_code,
            OTP.phone == phone,
            OTP.used == False,  # noqa: E712
            OTP.expires_at > _utcnow_naive(),
        )
        .first()
    )


def get_latest_unused_otp(db: Session, phone: str) -> OTP | None:
    """Latest unused OTP for a phone (used by the dev-otp endpoint)."""
    return (
        db.query(OTP)
        .filter(OTP.phone == phone, OTP.used == False)  # noqa: E712
        .order_by(OTP.created_at.desc())
        .first()
    )
