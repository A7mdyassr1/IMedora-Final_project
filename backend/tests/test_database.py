from sqlalchemy import text

from app.core import database
from app.core.database import get_db, get_engine, safe_database_url


class _FakeSession:
    def __init__(self):
        self.rolled_back = False
        self.closed = False

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_get_db_closes_session_after_request(monkeypatch):
    fake = _FakeSession()
    monkeypatch.setattr(database, "get_session_factory", lambda: (lambda: fake))
    gen = get_db()
    assert next(gen) is fake
    gen.close()
    assert fake.closed and not fake.rolled_back


def test_get_db_rolls_back_on_error(monkeypatch):
    fake = _FakeSession()
    monkeypatch.setattr(database, "get_session_factory", lambda: (lambda: fake))
    gen = get_db()
    next(gen)
    try:
        gen.throw(RuntimeError("boom"))
    except RuntimeError:
        pass
    assert fake.rolled_back and fake.closed


def test_safe_database_url_hides_password():
    password = get_engine().url.password
    assert password
    assert safe_database_url() == get_engine().url.render_as_string(hide_password=True)
    assert "***" in safe_database_url()


# ---- real PostgreSQL (skipped unless TEST_DATABASE_URL is set) -------------
def test_postgres_connectivity(real_db_url):
    with get_engine().connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1


def test_connected_to_the_existing_imedora_schema(real_db_url):
    with get_engine().connect() as conn:
        assert conn.execute(text("SELECT to_regclass('public.devices')")).scalar() is not None
        assert conn.execute(text("SELECT COUNT(*) FROM alembic_version")).scalar() == 1
