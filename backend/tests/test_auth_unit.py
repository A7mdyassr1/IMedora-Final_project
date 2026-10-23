"""Auth behaviour that is decided BEFORE any database access (no PostgreSQL needed)."""
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from fastapi import Depends
from pydantic import ValidationError

from app.api.deps import get_current_user, require_roles
from app.core.config import get_settings
from app.core.roles import Role
from app.schemas.user import UserCreate, UserUpdate


def _expired_token():
    return jwt.encode(
        {"sub": str(uuid.uuid4()), "exp": datetime.now(timezone.utc) - timedelta(minutes=5)},
        get_settings().jwt_secret_key.get_secret_value(),
        algorithm="HS256",
    )


@pytest.mark.parametrize("path", ["/api/v1/auth/me", "/api/v1/users"])
def test_protected_routes_require_a_token(client, path):
    r = client.get(path)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "unauthorized"
    assert r.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("token", ["garbage", None])
def test_invalid_or_expired_token_is_401(client, token):
    token = token or _expired_token()
    r = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


def test_login_body_is_validated(client):
    assert client.post("/api/v1/auth/login", json={"identifier": "a@b.co"}).status_code == 422
    assert client.post("/api/v1/auth/login", json={}).status_code == 422


def test_login_error_does_not_echo_the_password(client):
    r = client.post("/api/v1/auth/login", json={"identifier": "", "password": "hunter2-secret"})
    assert r.status_code == 422 and "hunter2-secret" not in r.text


def test_require_roles_allows_and_denies(app, client):
    @app.get("/__t/admin-only")
    def _admin_only(user=Depends(require_roles(Role.ADMIN))):
        return {"ok": True}

    def as_role(name):
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(role=SimpleNamespace(name=name))

    as_role("technician")
    r = client.get("/__t/admin-only")
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    as_role("admin")
    assert client.get("/__t/admin-only").status_code == 200


# ---- schemas -----------------------------------------------------------------
BASE = dict(full_name="Sara", password="Correct-Horse-9", role="technician", hospital_id=str(uuid.uuid4()))


def test_email_is_normalised_and_reserved_domains_are_allowed():
    assert UserCreate(email="  Demo@Imedora.LOCAL ", **BASE).email == "demo@imedora.local"


@pytest.mark.parametrize("bad", ["nope", "a@b", "a b@c.de", ""])
def test_bad_emails_rejected(bad):
    with pytest.raises(ValidationError):
        UserCreate(email=bad, **BASE)


def test_short_password_and_unknown_role_rejected():
    with pytest.raises(ValidationError):
        UserCreate(email="a@b.co", **{**BASE, "password": "short"})
    with pytest.raises(ValidationError):
        UserCreate(email="a@b.co", **{**BASE, "role": "viewer"})


def test_update_only_reports_sent_fields_and_rejects_nulling_required_ones():
    assert UserUpdate(full_name="X").model_dump(exclude_unset=True) == {"full_name": "X"}
    assert UserUpdate(department_id=None).model_dump(exclude_unset=True) == {"department_id": None}  # allowed: clears it
    with pytest.raises(ValidationError):
        UserUpdate(is_active=None)
