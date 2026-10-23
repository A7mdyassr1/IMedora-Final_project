"""
Application settings - everything environment-driven, nothing hardcoded.

Values come from real environment variables first, then from the
repository-root `.env` (the same file database/ already uses). The
database URL is a SecretStr so it can never leak through repr()/logs.
"""
from functools import lru_cache
from pathlib import Path
from typing import List, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py -> parents[3] is the repository root
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",  # the shared .env also holds variables for other services
    )

    app_name: str = "IMedora API"
    app_version: str = "0.1.0"
    app_env: Literal["development", "test", "production"] = "development"
    api_v1_prefix: str = "/api/v1"

    # Required: no default on purpose, the app must not start pointed at a guess.
    database_url: SecretStr

    # Required, no default: a default signing key would be a published secret.
    jwt_secret_key: SecretStr
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_expire_minutes: int = Field(default=60, ge=1, le=1440)

    db_pool_size: int = Field(default=5, ge=1)
    db_max_overflow: int = Field(default=10, ge=0)
    db_pool_timeout: int = Field(default=30, ge=1)
    db_connect_timeout: int = Field(default=5, ge=1)

    # Comma-separated list, e.g. "http://localhost:3000,https://imedora.hospital.local"
    cors_origins: str = "http://localhost:3000"

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_json: bool = True

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_log_level(cls, value):
        return value.upper() if isinstance(value, str) else value

    @field_validator("database_url")
    @classmethod
    def _must_be_postgres(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith("postgresql"):
            raise ValueError("DATABASE_URL must be a PostgreSQL URL (postgresql+psycopg2://...)")
        return value

    @field_validator("jwt_secret_key")
    @classmethod
    def _strong_secret(cls, value: SecretStr) -> SecretStr:
        if len(value.get_secret_value()) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 characters (see .env.example)")
        return value

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Cached settings singleton - import this, don't construct Settings() directly."""
    return Settings()
