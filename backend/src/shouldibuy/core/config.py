"""Application configuration via pydantic-settings."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings. Override via environment variables (prefix ``SHOULDIBUY_``)."""

    model_config = SettingsConfigDict(
        env_prefix="SHOULDIBUY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "shouldibuy-api"
    environment: str = "local"
    log_level: str = "INFO"

    # CORS — comma-separated origins allowed to hit the API/SSE routes.
    cors_origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

    # M0 staged-pipeline delay between stages (seconds). Keep small for visible reveal.
    stage_delay_seconds: float = 0.4

    # TODO(M1): postgres + redis connection settings.
    # database_url: str = "postgresql+asyncpg://localhost/shouldibuy"
    # redis_url: str = "redis://localhost:6379/0"

    # TODO(M1): eBay OAuth credentials for the live Browse adapter.
    ebay_client_id: str | None = None
    ebay_client_secret: str | None = None
    ebay_oauth_url: str = "https://api.ebay.com/identity/v1/oauth2/token"
    ebay_browse_base_url: str = "https://api.ebay.com/buy/browse/v1"


_settings: Settings | None = None


def get_settings() -> Settings:
    """Return a cached Settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
