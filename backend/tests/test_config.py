import pytest
from pydantic import ValidationError

from app.core.config import Settings

URL = "postgresql+psycopg2://u:secretpw@localhost:5432/imedora"


def make(**kw):
    return Settings(_env_file=None, **kw)


def test_cors_origins_are_split_and_trimmed():
    s = make(database_url=URL, cors_origins="http://a.example, http://b.example ,")
    assert s.cors_origins_list == ["http://a.example", "http://b.example"]


def test_non_postgres_url_is_rejected():
    with pytest.raises(ValidationError):
        make(database_url="sqlite:///dev.db")


def test_database_url_is_required(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_password_never_appears_in_repr():
    s = make(database_url=URL)
    assert "secretpw" not in repr(s) and "secretpw" not in str(s)


def test_log_level_is_case_insensitive():
    assert make(database_url=URL, log_level="debug").log_level == "DEBUG"
