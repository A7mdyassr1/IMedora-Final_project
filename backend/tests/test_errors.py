import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError, OperationalError

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError


@pytest.fixture
def err_app(app):
    @app.get("/__t/not-found")
    def _nf():
        raise NotFoundError("Device not found.")

    @app.get("/__t/conflict")
    def _cf():
        raise ConflictError("Device code already exists.")

    @app.get("/__t/bad")
    def _bad():
        raise BadRequestError()

    @app.get("/__t/int")
    def _int(n: int):
        return {"n": n}

    @app.get("/__t/integrity")
    def _integrity():
        raise IntegrityError("INSERT ...", {}, Exception('duplicate key violates constraint "uq_device_hospital_code"'))

    @app.get("/__t/operational")
    def _op():
        raise OperationalError("SELECT 1", {}, Exception("could not connect to server at 10.0.0.5"))

    @app.get("/__t/boom")
    def _boom():
        raise RuntimeError("secret internal detail")

    return app


@pytest.fixture
def ec(err_app):
    # raise_server_exceptions=False so the 500 handler's response is observable
    with TestClient(err_app, raise_server_exceptions=False) as c:
        yield c


def test_app_errors_map_to_status_and_body(ec):
    r = ec.get("/__t/not-found")
    assert (r.status_code, r.json()) == (404, {"error": {"code": "not_found", "message": "Device not found."}})
    assert ec.get("/__t/conflict").status_code == 409
    assert ec.get("/__t/bad").status_code == 400


def test_validation_error_is_422_with_field_details(ec):
    r = ec.get("/__t/int", params={"n": "abc"})
    assert r.status_code == 422
    body = r.json()["error"]
    assert body["code"] == "validation_error"
    assert body["details"][0]["field"] == "query.n"
    assert "input" not in r.text  # pydantic's input echo is stripped


def test_integrity_error_is_409_without_raw_postgres_text(ec):
    r = ec.get("/__t/integrity")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "conflict"
    assert "uq_device_hospital_code" not in r.text


def test_operational_error_is_503_without_host_details(ec):
    r = ec.get("/__t/operational")
    assert r.status_code == 503
    assert "10.0.0.5" not in r.text


def test_unexpected_exception_is_500_and_safe(ec):
    r = ec.get("/__t/boom")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal_error"
    assert "secret internal detail" not in r.text
