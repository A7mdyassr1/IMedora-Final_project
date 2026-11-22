from sqlalchemy import create_engine, text

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


def test_safe_database_url_hides_password(monkeypatch):
    # Review finding 4: the old version checked that the configured password was not a
    # SUBSTRING of the masked URL, so it failed whenever the password also appeared in the
    # user or database name (e.g. password "test" + database "imedora_test") even though
    # masking worked, and passed or failed depending on local credentials. Use a sentinel
    # password that cannot occur anywhere else in the URL instead.
    sentinel = "S3ntinel-Pw-7f3a9c"
    engine = create_engine(f"postgresql+psycopg2://imedora:{sentinel}@db.example:5432/imedora_test")  # never connects
    monkeypatch.setattr(database, "get_engine", lambda: engine)

    masked = safe_database_url()
    assert sentinel not in masked
    assert masked == "postgresql+psycopg2://imedora:***@db.example:5432/imedora_test"


def test_configured_url_is_masked_exactly():
    """Whatever DATABASE_URL is in use, the masked form is that URL with only the password replaced."""
    url = get_engine().url
    masked = safe_database_url()
    credentials, location = masked.split("://", 1)[1].split("@", 1)
    assert credentials == f"{url.username}:***"
    assert location == url.render_as_string(hide_password=False).split("@", 1)[1]  # host, port, database unchanged


# ---- real PostgreSQL (skipped unless TEST_DATABASE_URL is set) -------------
def test_postgres_connectivity(real_db_url):
    with get_engine().connect() as conn:
        assert conn.execute(text("SELECT 1")).scalar() == 1


def test_connected_to_the_existing_imedora_schema(real_db_url):
    with get_engine().connect() as conn:
        assert conn.execute(text("SELECT to_regclass('public.devices')")).scalar() is not None
        assert conn.execute(text("SELECT COUNT(*) FROM alembic_version")).scalar() == 1
