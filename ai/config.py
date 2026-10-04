"""
AI subsystem configuration.

Everything here is environment-driven - no API keys, models, or
provider choices are hardcoded anywhere in the codebase. Copy
`.env.example` to `.env` and fill in real values when you have a real
LLM/embedding provider; every default below runs against the mock
implementations with no external calls at all, so the AI layer works
out of the box before any provider is configured.
"""
from functools import lru_cache
from typing import Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class AISettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Which concrete DataProvider to wire up - "mock" until the backend exists.
    data_provider: Literal["mock", "backend"] = "mock"

    # LLM provider configuration (Phase AI-7).
    llm_provider: Literal["mock", "anthropic", "openai"] = "mock"
    llm_model: str = "mock-model"
    llm_api_key: Optional[str] = None

    # Embedding provider configuration (Phase AI-6/7).
    embedding_provider: Literal["mock", "openai", "local"] = "mock"
    embedding_model: str = "mock-embedding"

    # Vector store backend (Phase AI-6).
    vector_store_type: Literal["local", "pgvector", "qdrant"] = "local"

    # Backend API base URL - only used once data_provider="backend" (not built yet).
    backend_api_base_url: Optional[str] = None


@lru_cache
def get_settings() -> AISettings:
    """Cached settings singleton - import this, don't construct AISettings() directly."""
    return AISettings()
