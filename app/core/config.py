"""
Centralized application configuration.

Every environment-specific value (DB creds, secrets, limits, provider keys)
lives here and ONLY here. Loaded from environment variables / a .env file
via pydantic-settings, so the same code runs unchanged across local, docker,
and any future staging/prod deployment -- only the .env differs.
"""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- App ---
    APP_NAME: str = "Vendor Due Diligence Assistant"
    ENVIRONMENT: str = "local"  # local | staging | production
    DEBUG: bool = True  # shows generated SQL in logs -- useful while learning; set False in prod

    # --- Database ---
    # Async URL (asyncpg driver) -- used by both the running app and Alembic
    # migrations (we use alembic's async template, so no separate sync URL
    # is needed).
    DATABASE_URL: str = "sqlite+aiosqlite:///./vendor_dd.db"

    # --- Auth / JWT ---
    JWT_SECRET_KEY: str = "CHANGE_ME_IN_ENV"  # noqa: S105 - overridden via .env in real use
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 8  # 8 hour token

    # --- Seeded admin (created on startup if it doesn't exist) ---
    SEED_ADMIN_EMAIL: str = "admin@vendordd.internal-app.com"
    SEED_ADMIN_PASSWORD: str = "ChangeThisAdminPassword123!"

    # --- File upload constraints ---
    UPLOAD_DIR: str = "uploads"
    MAX_FILE_SIZE_MB: int = 25
    ALLOWED_EXTENSIONS: List[str] = [".pdf", ".docx", ".doc", ".txt", ".csv", ".xlsx"]

    # --- LLM provider (wired up from Milestone 2 onward) ---
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"

    @property
    def max_file_size_bytes(self) -> int:
        return self.MAX_FILE_SIZE_MB * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Cached so we parse the environment once per process, not per request."""
    return Settings()
