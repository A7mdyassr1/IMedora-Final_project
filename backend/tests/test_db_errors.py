"""Constraint-name -> message mapping (no database needed)."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.core.db_errors import describe_integrity_error


def pg_error(pgcode, constraint=None):
    orig = SimpleNamespace(pgcode=pgcode, diag=SimpleNamespace(constraint_name=constraint))
    return IntegrityError("INSERT ...", {}, orig)


@pytest.mark.parametrize(
    "pgcode, constraint, status, code, fragment",
    [
        ("23505", "uq_device_hospital_code", 409, "conflict", "device with this code already exists"),
        ("23505", "devices_qr_identifier_key", 409, "conflict", "QR identifier"),
        ("23514", "ck_device_warranty_after_installation", 422, "constraint_violation", "Warranty expiry"),
        ("23503", "devices_department_id_fkey", 409, "in_use", "still has devices"),
        ("23503", "devices_device_model_id_fkey", 409, "in_use", "used by devices"),
        ("23505", "some_unknown_constraint", 409, "conflict", "already exists"),
        ("23514", None, 422, "constraint_violation", "data rule"),
        (None, None, 409, "conflict", "conflicts with existing data"),  # no pgcode at all
    ],
)
def test_mapping(pgcode, constraint, status, code, fragment):
    s, c, message = describe_integrity_error(pg_error(pgcode, constraint))
    assert (s, c) == (status, code)
    assert fragment in message


def test_handler_returns_mapped_error_and_hides_sql(app):
    @app.get("/__t/dup")
    def _dup():
        raise pg_error("23505", "uq_device_hospital_code")

    @app.get("/__t/check")
    def _check():
        raise pg_error("23514", "ck_device_warranty_after_installation")

    with TestClient(app, raise_server_exceptions=False) as c:
        r = c.get("/__t/dup")
        assert r.status_code == 409
        assert r.json()["error"]["message"] == "A device with this code already exists in this hospital."
        assert "uq_device_hospital_code" not in r.text and "INSERT" not in r.text
        r = c.get("/__t/check")
        assert r.status_code == 422 and r.json()["error"]["code"] == "constraint_violation"
