"""Application settings.

Uses pydantic-settings so values can be injected via environment variables
(or a `.env` file). All values have sensible dev defaults so the service runs
out of the box; override them in production via env vars.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Database ---
    # Named AUTH_DATABASE_URL to avoid clashing with any sibling service that
    # also exposes a DATABASE_URL env var (e.g. a Prisma-based app).
    AUTH_DATABASE_URL: str = "sqlite:///./data/app.db"

    # --- JWT ---
    SECRET_KEY: str = "change-this-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # --- OTP ---
    OTP_EXPIRE_MINUTES: int = 5
    OTP_LENGTH: int = 6

    # --- App ---
    APP_NAME: str = "Options Trading"
    APP_VERSION: str = "1.0.0"
    CORS_ORIGINS: list[str] = ["*"]

    # --- TrueData (sandbox defaults; override via env in production) ---
    # Trial credentials provided by TrueData — sandbox environment.
    TRUEDATA_USERNAME: str = "Trial126"
    TRUEDATA_PASSWORD: str = "sand126"
    TRUEDATA_LIVE_PORT: int = 8086  # Real-Time + History trial port
    TRUEDATA_URL: str = "push.truedata.in"
    TRUEDATA_HIST_URL: str = "https://history.truedata.in"
    # Hard ceiling on rows written per symbol into a single .xls sheet.
    # BIFF8 .xls has a hard 65536-row limit; we default to 60000 to leave
    # room for the header row.
    TRUEDATA_MAX_ROWS_PER_SYMBOL: int = 60000
    # Network timeout (seconds) for the full TrueData connect+fetch+disconnect
    # cycle per request.
    TRUEDATA_REQUEST_TIMEOUT_SEC: int = 60

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    @property
    def DATABASE_URL(self) -> str:
        """Backwards-compatible accessor used by the database module."""
        return self.AUTH_DATABASE_URL


settings = Settings()
