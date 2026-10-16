from sqlalchemy.exc import OperationalError

from app.core.database import get_db


class _OkSession:
    def execute(self, *a, **k):
        return None

    def rollback(self):
        pass

    def close(self):
        pass


class _BrokenSession(_OkSession):
    def execute(self, *a, **k):
        raise OperationalError("SELECT 1", {}, Exception("password=hunter2 host=secret-db.internal"))


def _override_with(app, session):
    def dependency():  # must be a real generator function, like get_db itself
        yield session

    app.dependency_overrides[get_db] = dependency


def test_app_starts_and_serves_requests(client):
    # `client` entered the lifespan. Without a reachable DB the startup check only logs; it must not crash.
    assert client.get("/health").status_code == 200


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_versioned_health_ok(client):
    r = client.get("/api/v1/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_unknown_route_uses_standard_error_shape(client):
    r = client.get("/nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"


def test_docs_are_exposed(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    assert "/health/db" in client.get("/openapi.json").json()["paths"]


def test_health_db_ok(app, client):
    _override_with(app, _OkSession())
    r = client.get("/health/db")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": "up"}


def test_health_db_unavailable_is_503_and_leaks_nothing(app, client):
    _override_with(app, _BrokenSession())
    r = client.get("/health/db")
    assert r.status_code == 503
    assert r.json() == {"status": "unavailable", "database": "unreachable"}
    assert "hunter2" not in r.text and "secret-db" not in r.text


def test_cors_preflight_for_allowed_origin(client):
    r = client.options(
        "/health",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_cors_blocks_unlisted_origin(client):
    r = client.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers


# ---- real PostgreSQL (skipped unless TEST_DATABASE_URL is set) -------------
def test_health_db_against_real_postgres(client, real_db_url):
    r = client.get("/health/db")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "database": "up"}
