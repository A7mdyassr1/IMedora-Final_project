"""
The ONE place that decides which concrete DataProvider an agent/tool
gets. Everything else in the AI layer calls `get_data_provider()` and
never constructs MockDataProvider or BackendDataProvider directly - so
switching the whole system over once the backend exists is a one-line
change to AISettings.data_provider (or the DATA_PROVIDER env var),
not a code change scattered across every agent.
"""
from ai.config import get_settings
from ai.services.data.base import DataProvider
from ai.services.data.mock_provider import MockDataProvider


def get_data_provider() -> DataProvider:
    settings = get_settings()
    if settings.data_provider == "mock":
        return MockDataProvider()
    if settings.data_provider == "backend":
        raise NotImplementedError(
            "BackendDataProvider doesn't exist yet - the backend hasn't been built. "
            "Set DATA_PROVIDER=mock until it has."
        )
    raise ValueError(f"Unknown data_provider setting: {settings.data_provider!r}")
