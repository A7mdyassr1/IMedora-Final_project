"""Password hashing (Argon2id) and JWT access tokens. No database access here."""
import uuid
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Tuple

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedError

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """False for a wrong password AND for a non-Argon2 value such as the
    placeholder hash the dev seeds put in users.password_hash."""
    try:
        return _hasher.verify(password_hash, password)
    except (VerificationError, InvalidHashError):
        return False


@lru_cache
def dummy_hash() -> str:
    """Verified against when the email is unknown, so 'no such user' and
    'wrong password' take about the same time."""
    return _hasher.hash("imedora-timing-equaliser")


def create_access_token(user_id: uuid.UUID) -> Tuple[str, int]:
    """Returns (token, expires_in_seconds). The token carries only the user id;
    role and active status are re-read from the database on every request."""
    s = get_settings()
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=s.access_token_expire_minutes)
    token = jwt.encode(
        {"sub": str(user_id), "iat": now, "exp": exp},
        s.jwt_secret_key.get_secret_value(),
        algorithm=s.jwt_algorithm,
    )
    return token, s.access_token_expire_minutes * 60


def decode_access_token(token: str) -> uuid.UUID:
    s = get_settings()
    try:
        payload = jwt.decode(
            token,
            s.jwt_secret_key.get_secret_value(),
            algorithms=[s.jwt_algorithm],  # pinned: rejects alg=none and algorithm swaps
            options={"require": ["exp", "sub"]},
        )
        return uuid.UUID(payload["sub"])
    except (jwt.PyJWTError, ValueError, KeyError, TypeError):
        raise UnauthorizedError("Invalid or expired token.")
