"""Database engine + session management.

`get_db` is the FastAPI dependency used by every route that needs a session.
`init_db` creates all tables — called once from the app's startup lifespan.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """Declarative base shared by all models."""


# `check_same_thread=False` is required for SQLite + FastAPI's threadpool.
engine = create_engine(
    settings.DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a scoped DB session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Called on application startup."""
    # Import models so they are registered on Base.metadata before create_all.
    from app.models import otp, user  # noqa: F401

    Base.metadata.create_all(bind=engine)
