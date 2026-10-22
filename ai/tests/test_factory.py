"""
Factory tests - confirms the mock/backend switch actually works.

Run with:
    python -m pytest ai/tests/test_factory.py -v
"""
import pytest

from ai.config import get_settings
from ai.services.data.factory import get_data_provider
from ai.services.data.mock_provider import MockDataProvider


def test_default_settings_give_a_mock_provider():
    get_settings.cache_clear()
    provider = get_data_provider()
    assert isinstance(provider, MockDataProvider)


def test_backend_setting_raises_clear_not_implemented_error(monkeypatch):
    monkeypatch.setenv("DATA_PROVIDER", "backend")
    get_settings.cache_clear()
    with pytest.raises(NotImplementedError, match="backend hasn't been built"):
        get_data_provider()
    monkeypatch.delenv("DATA_PROVIDER", raising=False)
    get_settings.cache_clear()
