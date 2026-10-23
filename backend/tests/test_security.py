from datetime import datetime, timedelta, timezone
import uuid

import jwt
import pytest

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def _secret():
    return get_settings().jwt_secret_key.get_secret_value()


def test_hash_roundtrip_and_salting():
    h = hash_password("Correct-Horse-9")
    assert h != "Correct-Horse-9" and h.startswith("$argon2")
    assert verify_password("Correct-Horse-9", h)
    assert not verify_password("wrong-password", h)
    assert hash_password("Correct-Horse-9") != h  # random salt


def test_placeholder_seed_hash_never_verifies():
    # database/seeds put 'not-a-real-hash' in users.password_hash
    assert verify_password("anything", "not-a-real-hash") is False


def test_token_roundtrip():
    uid = uuid.uuid4()
    token, expires_in = create_access_token(uid)
    assert expires_in == get_settings().access_token_expire_minutes * 60
    assert decode_access_token(token) == uid


def _forge(payload, key=None, alg="HS256"):
    return jwt.encode(payload, key if key is not None else _secret(), algorithm=alg)


def _now():
    return datetime.now(timezone.utc)


@pytest.mark.parametrize(
    "token",
    [
        "not-a-jwt",
        _forge({"sub": str(uuid.uuid4()), "exp": _now() - timedelta(minutes=1)}),          # expired
        _forge({"sub": str(uuid.uuid4()), "exp": _now() + timedelta(hours=1)}, key="x" * 40),  # wrong key
        _forge({"sub": str(uuid.uuid4()), "exp": _now() + timedelta(hours=1)}, key="", alg="none"),  # alg=none
        _forge({"exp": _now() + timedelta(hours=1)}),                                       # no sub
        _forge({"sub": str(uuid.uuid4())}),                                                 # no exp
        _forge({"sub": "not-a-uuid", "exp": _now() + timedelta(hours=1)}),                  # bad sub
    ],
)
def test_bad_tokens_are_rejected(token):
    with pytest.raises(UnauthorizedError):
        decode_access_token(token)
