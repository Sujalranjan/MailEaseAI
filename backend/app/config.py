from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration, loaded from environment variables / .env.

    Only settings needed by the current phase (IMAP email fetch +
    database persistence) are defined here. Settings for later phases
    (Google OAuth, LLM provider) will be added when those phases are
    implemented, rather than declared unused ahead of time.
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Mail-Ease"
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    )

    # IMAP / email account — required for the /emails endpoint to function.
    # Left optional at the settings level so the app can still start (and
    # /health can report the missing configuration) without them set.
    email_address: str | None = None
    email_app_password: str | None = None
    imap_server: str = "imap.gmail.com"
    imap_port: int = 993
    max_emails_per_fetch: int = 50

    # Database. SQLite for local dev; the URL is the only thing that needs
    # to change to move to PostgreSQL later (e.g.
    # postgresql+psycopg://user:pass@host/db) since access goes through
    # SQLAlchemy everywhere.
    database_url: str = "sqlite:///./mailease.db"

    def imap_is_configured(self) -> bool:
        return bool(self.email_address and self.email_app_password)


@lru_cache
def get_settings() -> Settings:
    return Settings()
