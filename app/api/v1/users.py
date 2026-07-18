"""User routes: current-user profile."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas import UserResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get(
    "/me",
    response_model=UserResponse,
    summary="Get the current authenticated user",
)
def get_current_user_profile(
    current_user: User = Depends(get_current_user),
    _db: Session = Depends(get_db),
):
    """Returns the profile of the user identified by the bearer token."""
    return current_user
