import pytest
from pydantic import ValidationError

from app.core.config import Settings

URL = "postgresql+psycopg2://u:secretpw@localhost:5432/imedora"
SECRET = "k" * 40


def make(**kw):
    kw.setdefault("jwt_secret_key", SECRET)
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
        Settings(_env_file=None, jwt_secret_key=SECRET)


def test_jwt_secret_is_required_and_must_be_long(monkeypatch):
    monkeypatch.delenv("JWT_SECRET_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, database_url=URL)
    with pytest.raises(ValidationError):
        make(database_url=URL, jwt_secret_key="short")


def test_jwt_secret_never_appears_in_repr():
    assert SECRET not in repr(make(database_url=URL))


def test_password_never_appears_in_repr():
    s = make(database_url=URL)
    assert "secretpw" not in repr(s) and "secretpw" not in str(s)


def test_access_token_lifetime_defaults_to_one_shift(monkeypatch):
    monkeypatch.delenv("ACCESS_TOKEN_EXPIRE_MINUTES", raising=False)
    assert make(database_url=URL).access_token_expire_minutes == 480


def test_access_token_lifetime_is_configurable_within_bounds(monkeypatch):
    monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60")
    assert make(database_url=URL).access_token_expire_minutes == 60
    for bad in ("0", "1441"):
        monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", bad)
        with pytest.raises(ValidationError):
            make(database_url=URL)


def test_log_level_is_case_insensitive():
    assert make(database_url=URL, log_level="debug").log_level == "DEBUG"
