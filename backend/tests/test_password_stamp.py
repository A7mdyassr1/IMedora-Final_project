"""Password stamp (Decision 2, B3.1 CP2): a password change or reset invalidates every token
issued before it. The first half needs no database; the second runs against real PostgreSQL."""
import uuid
from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import get_settings
from app.core.security import (
    STAMP_CLAIM, create_access_token, decode_access_token, decode_token, password_stamp, stamp_matches,
)
from tests.world import API, PW, auth, login

HASH_A = "$argon2id$v=19$m=65536,t=3,p=4$aaaa$bbbb"
HASH_B = "$argon2id$v=19$m=65536,t=3,p=4$cccc$dddd"


# ---- no database ------------------------------------------------------------------------
def test_stamp_is_stable_for_the_same_hash_and_changes_with_it():
    assert password_stamp(HASH_A) == password_stamp(HASH_A)
    assert password_stamp(HASH_A) != password_stamp(HASH_B)
    assert len(password_stamp(HASH_A)) == 32


def test_stamp_reveals_nothing_of_the_hash():
    stamp = password_stamp(HASH_A)
    assert "argon2" not in stamp and HASH_A[-4:] not in stamp


def test_stamp_depends_on_the_server_secret(monkeypatch):
    before = password_stamp(HASH_A)
    monkeypatch.setenv("JWT_SECRET_KEY", "another-secret-" + "y" * 40)
    get_settings.cache_clear()
    try:
        assert password_stamp(HASH_A) != before
    finally:
        monkeypatch.undo()
        get_settings.cache_clear()


def test_login_tokens_carry_the_stamp_and_decode_keeps_working():
    uid = uuid.uuid4()
    token, _ = create_access_token(uid, HASH_A)
    claims = decode_token(token)
    assert claims.user_id == uid and claims.password_stamp == password_stamp(HASH_A)
    assert decode_access_token(token) == uid  # existing helper unchanged


def test_stamp_matching():
    assert stamp_matches(password_stamp(HASH_A), HASH_A)
    assert not stamp_matches(password_stamp(HASH_A), HASH_B)
    assert not stamp_matches(None, HASH_A) and not stamp_matches("", HASH_A)
    assert not stamp_matches("ünïcödé-stamp", HASH_A)  # never raises


# ---- real PostgreSQL --------------------------------------------------------------------
def _me(client, headers):
    return client.get(f"{API}/auth/me", headers=headers).status_code


def _forge(user_id: str, **extra) -> dict:
    """A correctly SIGNED token (server secret) with chosen claims."""
    s = get_settings()
    claims = {"sub": user_id, "iat": datetime.now(timezone.utc), "exp": datetime.now(timezone.utc) + timedelta(hours=1), **extra}
    return {"Authorization": "Bearer " + jwt.encode(claims, s.jwt_secret_key.get_secret_value(), algorithm=s.jwt_algorithm)}


def test_existing_login_and_token_use_still_work(client, world):
    r = login(client, world["tech"])
    assert r.status_code == 200 and set(r.json()) >= {"access_token", "token_type", "expires_in", "user"}
    h = {"Authorization": f"Bearer {r.json()['access_token']}"}
    assert _me(client, h) == 200 and _me(client, h) == 200  # reusable until it expires


def test_own_password_change_invalidates_earlier_tokens(client, world):
    first, second = auth(client, world["staff"]), auth(client, world["staff"])  # e.g. phone + tablet
    r = client.post(f"{API}/auth/change-password", headers=first,
                    json={"current_password": PW, "new_password": "Brand-New-Pass-1"})
    assert r.status_code == 204 and r.content == b""  # contract unchanged: 204, no body, no new token
    assert _me(client, first) == 401 and _me(client, second) == 401  # every earlier token is dead
    assert client.get(f"{API}/auth/me", headers=first).json()["error"]["message"] == "Invalid or expired token."
    fresh = login(client, world["staff"], "Brand-New-Pass-1")
    assert fresh.status_code == 200
    assert _me(client, {"Authorization": f"Bearer {fresh.json()['access_token']}"}) == 200


def test_admin_reset_invalidates_the_users_tokens_but_not_the_admins(client, world):
    tech = auth(client, world["tech"])
    admin = auth(client, world["admin"])
    assert client.post(f"{API}/users/{world['tech_id']}/reset-password", headers=admin,
                       json={"new_password": "Reset-By-Admin-1"}).status_code == 204
    assert _me(client, tech) == 401
    assert _me(client, admin) == 200


def test_tokens_without_a_stamp_or_with_a_wrong_one_are_rejected(client, world):
    me = client.get(f"{API}/auth/me", headers=auth(client, world["tech"])).json()["id"]
    assert _me(client, _forge(me)) == 401  # signed correctly, but issued before stamps existed
    assert _me(client, _forge(me, **{STAMP_CLAIM: "0" * 32})) == 401
    assert _me(client, _forge(me, **{STAMP_CLAIM: 12345})) == 401  # wrong type


def test_a_stamp_for_another_password_is_rejected(client, world):
    me = client.get(f"{API}/auth/me", headers=auth(client, world["tech"])).json()["id"]
    assert _me(client, _forge(me, **{STAMP_CLAIM: password_stamp(HASH_A)})) == 401
