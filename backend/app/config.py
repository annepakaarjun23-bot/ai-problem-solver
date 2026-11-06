"""Application settings, loaded from environment variables (and an optional .env file)."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PLACEHOLDER_API_KEY = "your_api_key_here"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[2] / ".env",
        extra="ignore",
    )

    ENVIRONMENT: str = "development"  # "production" enables stricter checks

    # Application database (SQLAlchemy async driver).
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_problem_solver"

    # Optional direct database connection reserved for Alembic migrations.
    # The application continues to use DATABASE_URL for normal queries.
    MIGRATION_DATABASE_URL: str = ""

    # Authentication
    JWT_SECRET_KEY: str = "dev-only-insecure-secret-change-me-0000000000"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_MINUTES: int = 15
    REFRESH_TOKEN_DAYS: int = 14
    REFRESH_COOKIE_NAME: str = "refresh_token"
    COOKIE_SECURE: bool = True  # set to false only while serving over plain HTTP
    # Comma-separated list of browser origins allowed to call the API with cookies.
    ALLOWED_ORIGINS: str = "http://localhost:8080,http://localhost:5173"

    # AI provider (OpenAI-compatible). The key is optional so the app can start without it.
    AI_ROUTER_API_KEY: str = ""
    AI_ROUTER_BASE_URL: str = "https://api.airouter.in/v1"
    AI_ROUTER_MODEL: str = "openai/gpt-6-luna"
    AI_REQUEST_TIMEOUT: float = 120.0  # seconds without provider data before timing out
    AI_STREAM_USAGE: bool = True  # ask the provider to report token usage in the stream

    # Context window management (rough token estimate: 1 token ~ 4 characters)
    CONTEXT_TOKEN_BUDGET: int = 12000
    CONTEXT_MAX_MESSAGES: int = 60

    @property
    def allowed_origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]

    @property
    def ai_configured(self) -> bool:
        key = self.AI_ROUTER_API_KEY.strip()
        return bool(key) and key != PLACEHOLDER_API_KEY

    @property
    def checkpointer_dsn(self) -> str:
        """psycopg-style DSN for the LangGraph PostgreSQL checkpointer."""
        return self.DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)

    def validate_for_runtime(self) -> None:
        """Refuse to start in production with an unsafe configuration."""
        if self.ENVIRONMENT.lower() == "production":
            secret = self.JWT_SECRET_KEY
            if len(secret) < 32 or secret.startswith(("change-me", "dev-only")):
                raise RuntimeError(
                    "JWT_SECRET_KEY must be a random string of at least 32 characters in production."
                )


@lru_cache
def get_settings() -> Settings:
    return Settings()
