"""Authentication routes: OTP request, register, login."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.schemas import (
    DevOtpResponse,
    LoginRequest,
    OTPRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.services import jwt_service, otp_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/request-otp",
    status_code=status.HTTP_200_OK,
    summary="Request OTP for registration",
)
def request_otp(request: OTPRequest, db: Session = Depends(get_db)):
    """Generate a registration OTP. Fails if the phone is already registered."""
    existing = db.query(User).filter(User.phone == request.phone).first()
    if existing and existing.is_verified:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User already registered, use login",
        )

    otp_service.create_otp(db, request.country_code, request.phone, purpose="register")
    return {"message": "OTP sent successfully"}


@router.post(
    "/request-login-otp",
    status_code=status.HTTP_200_OK,
    summary="Request OTP for login",
)
def request_login_otp(request: OTPRequest, db: Session = Depends(get_db)):
    """Generate a login OTP. Fails if the user doesn't exist or isn't verified."""
    user = db.query(User).filter(User.phone == request.phone).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User not verified"
        )

    otp_service.create_otp(db, request.country_code, request.phone, purpose="login")
    return {"message": "OTP sent successfully"}


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
)
def register(request: RegisterRequest, db: Session = Depends(get_db)):
    """Verify the OTP and create a new user account."""
    success, message = otp_service.verify_otp(
        db, request.country_code, request.phone, request.code
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=message
        )

    existing = db.query(User).filter(User.phone == request.phone).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phone number already registered",
        )

    user = User(
        country_code=request.country_code,
        phone=request.phone,
        is_verified=True,
        name=request.name,
        email=request.email,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.post(
    "/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Login with OTP",
)
def login(request: LoginRequest, db: Session = Depends(get_db)):
    """Verify the OTP and return a JWT access token."""
    user = db.query(User).filter(User.phone == request.phone).first()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )
    if not user.is_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="User not verified"
        )

    success, message = otp_service.verify_otp(
        db, request.country_code, request.phone, request.code
    )
    if not success:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail=message
        )

    token = jwt_service.create_access_token(
        data={"sub": user.id, "phone": user.phone, "country_code": user.country_code}
    )
    return {"access_token": token, "token_type": "bearer"}


@router.get(
    "/dev-otp",
    response_model=DevOtpResponse,
    status_code=status.HTTP_200_OK,
    summary="DEV ONLY — fetch the latest OTP",
)
def dev_get_latest_otp(phone: str, db: Session = Depends(get_db)):
    """DEV ONLY — OTP is mock (not sent via SMS), so this returns the latest
    unused OTP for a phone so a client can display it during development."""
    otp = otp_service.get_latest_unused_otp(db, phone)
    if not otp:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No OTP found for this phone",
        )
    return {
        "phone": otp.phone,
        "code": otp.code,
        "expires_at": otp.expires_at,
        "purpose": otp.purpose,
    }
