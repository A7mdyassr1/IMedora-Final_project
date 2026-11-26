"""B9 CP1 - the read-only AI token (Decision 7, conditions 1 and 4; handover section J item 10).

The backend will give the AI service, for one chat request, a token of the requesting user that can
only READ: short-lived (AI_TOKEN_EXPIRE_MINUTES, default 5), password-stamped, `scp = "read"`.
Every signed-in endpoint goes through get_current_user, which refuses such a token on any method that
is not GET / HEAD / OPTIONS (403 `read_only_token`) and otherwise gives it exactly the user's scope.

The unit tests run without a database; the API tests need TEST_DATABASE_URL (the `world` fixture
removes everything it creates).
"""
import re
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from pydantic import ValidationError
from sqlalchemy import select, text

from app.api.deps import READ_METHODS, get_current_user
from app.core.config import Settings, get_settings
from app.core.database import get_session_factory
from app.core.exceptions import UnauthorizedError
from app.core.security import (
    READ_ONLY_SCOPE, SCOPE_CLAIM, STAMP_CLAIM, create_access_token, create_ai_token, decode_token, hash_password,
    password_stamp,
)
from app.models import User
from tests.world import API, PW, auth

HASH = hash_password("not-a-real-password-1")


def _sign(claims):
    s = get_settings()
    return jwt.encode(claims, s.jwt_secret_key.get_secret_value(), algorithm=s.jwt_algorithm)


# ---- unit: the token itself -----------------------------------------------------------------------------
def test_ai_token_claims_and_lifetime():
    uid = uuid.uuid4()
    before = datetime.now(timezone.utc)
    token, expires_in = create_ai_token(uid, HASH)
    payload = jwt.decode(token, options={"verify_signature": False})
    assert payload["sub"] == str(uid)
    assert payload[SCOPE_CLAIM] == READ_ONLY_SCOPE == "read"
    assert payload[STAMP_CLAIM] == password_stamp(HASH)               # mandatory: a password change ends it
    assert expires_in == 5 * 60                                       # default AI_TOKEN_EXPIRE_MINUTES
    lifetime = datetime.fromtimestamp(payload["exp"], timezone.utc) - before
    assert timedelta(minutes=5) - timedelta(seconds=5) <= lifetime <= timedelta(minutes=5, seconds=5)
    claims = decode_token(token)
    assert (claims.user_id, claims.scope, claims.read_only) == (uid, "read", True)


def test_login_tokens_are_unchanged():
    token, expires_in = create_access_token(uuid.uuid4(), HASH)
    payload = jwt.decode(token, options={"verify_signature": False})
    assert SCOPE_CLAIM not in payload and expires_in == 480 * 60
    claims = decode_token(token)
    assert (claims.scope, claims.read_only) == (None, False)


@pytest.mark.parametrize("scope", ["admin", "write", "", "READ", 1, ["read"]])
def test_any_other_scope_is_rejected(scope):
    now = datetime.now(timezone.utc)
    token = _sign({"sub": str(uuid.uuid4()), "iat": now, "exp": now + timedelta(minutes=5),
                   STAMP_CLAIM: password_stamp(HASH), SCOPE_CLAIM: scope})
    with pytest.raises(UnauthorizedError):
        decode_token(token)


@pytest.mark.parametrize("minutes, ok", [(0, False), (1, True), (5, True), (15, True), (16, False), (480, False)])
def test_ai_token_lifetime_stays_short(minutes, ok):
    base = dict(database_url="postgresql+psycopg2://u:p@h/db", jwt_secret_key="k" * 40)
    if ok:
        assert Settings(**base, ai_token_expire_minutes=minutes).ai_token_expire_minutes == minutes
    else:
        with pytest.raises(ValidationError):
            Settings(**base, ai_token_expire_minutes=minutes)


# ---- API: what the token may and may not do ---------------------------------------------------------------
def _user(email):
    with get_session_factory()() as db:
        return db.scalar(select(User).where(User.email == email))


def _ai(email):
    u = _user(email)
    return {"Authorization": f"Bearer {create_ai_token(u.id, u.password_hash)[0]}"}


def _signed_in_routes(app):
    """(METHOD, path with placeholder ids) of every operation that requires sign-in. Taken from the
    OpenAPI document: an operation lists the bearer scheme exactly when it depends on get_current_user,
    the only place the scheme is used (app/api/deps.py)."""
    for path, operations in app.openapi()["paths"].items():
        for method, op in operations.items():
            if any("HTTPBearer" in s for s in op.get("security", [])):
                yield method.upper(), re.sub(r"\{[^}]+\}", lambda _: str(uuid.uuid4()), path)


def test_the_sweep_sees_public_and_signed_in_endpoints_correctly(app):
    routes = set(_signed_in_routes(app))
    assert ("POST", f"{API}/auth/login") not in routes and ("POST", f"{API}/auth/forgot-password") not in routes
    assert ("GET", f"{API}/auth/me") in routes and ("POST", f"{API}/auth/change-password") in routes
    assert get_current_user.__name__ == "get_current_user"  # the dependency the sweep relies on


def _audit_rows():
    with get_session_factory()() as db:
        return db.scalar(text("SELECT count(*) FROM audit_logs"))


def test_every_write_endpoint_refuses_the_ai_token(app, client, world):
    writes = [(m, p) for m, p in _signed_in_routes(app) if m not in READ_METHODS]
    assert len(writes) > 40 and ("POST", f"{API}/tickets") in writes  # the sweep really covers the API
    headers, before = _ai(world["admin"]), _audit_rows()
    for method, path in writes:
        r = client.request(method, path, headers=headers, json={})
        assert r.status_code == 403, (method, path, r.status_code, r.text)
        assert r.json()["error"]["code"] == "read_only_token", (method, path, r.text)
    assert _audit_rows() == before                                    # nothing was written anywhere


def test_the_users_own_token_is_not_affected(client, world):
    r = client.post(f"{API}/auth/change-password", headers=auth(client, world["tech"]),
                    json={"current_password": "wrong-password", "new_password": "Another-password-123"})
    assert r.status_code == 400 and r.json()["error"]["code"] != "read_only_token"


def test_every_read_endpoint_accepts_it(app, client, world):
    headers = _ai(world["admin"])
    reads = [(m, p) for m, p in _signed_in_routes(app) if m == "GET"]
    assert len(reads) > 30
    for method, path in reads:
        r = client.request(method, path, headers=headers)
        assert r.status_code != 401, (path, r.text)
        if r.status_code == 403:
            assert r.json()["error"]["code"] != "read_only_token", (path, r.text)


@pytest.mark.parametrize("who", ["admin", "tech", "staff"])
def test_it_sees_exactly_what_the_user_sees(client, world, who):
    own, ai = auth(client, world[who]), _ai(world[who])
    for path in ("/auth/me", "/devices?page_size=100", "/tickets/mine", "/notifications",
                 f"/structure/hospitals/{world['h1']}"):
        mine, theirs = client.get(f"{API}{path}", headers=own), client.get(f"{API}{path}", headers=ai)
        assert (theirs.status_code, theirs.json()) == (mine.status_code, mine.json()), path


def test_another_organization_stays_invisible(client, world):
    r = client.get(f"{API}/structure/hospitals/{world['oh']}", headers=_ai(world["admin"]))
    assert r.status_code == 404


def test_it_ends_with_a_password_change(client, world):
    ai = _ai(world["tech"])
    assert client.get(f"{API}/auth/me", headers=ai).status_code == 200
    with get_session_factory()() as db:
        db.execute(text("UPDATE users SET password_hash = :h WHERE email = :e"), {"h": hash_password(PW + "x"),
                                                                                  "e": world["tech"]})
        db.commit()
    assert client.get(f"{API}/auth/me", headers=ai).status_code == 401


def test_it_ends_with_deactivation(client, world):
    ai = _ai(world["staff"])
    assert client.get(f"{API}/auth/me", headers=ai).status_code == 200
    with get_session_factory()() as db:
        db.execute(text("UPDATE users SET is_active = false WHERE email = :e"), {"e": world["staff"]})
        db.commit()
    assert client.get(f"{API}/auth/me", headers=ai).status_code == 401


def test_expired_unstamped_or_tampered_tokens_are_401_whatever_the_method(client, world):
    u = _user(world["admin"])
    now = datetime.now(timezone.utc)
    base = {"sub": str(u.id), "iat": now, SCOPE_CLAIM: READ_ONLY_SCOPE}
    bad = {
        "expired": _sign({**base, "exp": now - timedelta(seconds=1), STAMP_CLAIM: password_stamp(u.password_hash)}),
        "no stamp": _sign({**base, "exp": now + timedelta(minutes=5)}),
        "scope raised": _sign({**base, "exp": now + timedelta(minutes=5), STAMP_CLAIM: password_stamp(u.password_hash),
                               SCOPE_CLAIM: "admin"}),
    }
    for name, token in bad.items():
        h = {"Authorization": f"Bearer {token}"}
        assert client.get(f"{API}/auth/me", headers=h).status_code == 401, name
        assert client.post(f"{API}/tickets", headers=h, json={}).status_code == 401, name
