"""Password hashing (Argon2id) and JWT access tokens. No database access here."""
import hashlib
import hmac
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import Optional, Tuple

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


# ---- password stamp (Decision 2) -------------------------------------------------------
# Every token carries `pst`, a fingerprint of the user's password hash at login time. The API
# recomputes it on every request, so changing or resetting a password invalidates every token
# issued before. It is an HMAC keyed by a value derived from JWT_SECRET_KEY: it reveals nothing
# about the hash and cannot be forged without the server secret. No database column is needed.
STAMP_CLAIM = "pst"


def password_stamp(password_hash: str) -> str:
    secret = get_settings().jwt_secret_key.get_secret_value().encode()
    key = hmac.new(secret, b"imedora:password-stamp:v1", hashlib.sha256).digest()
    return hmac.new(key, password_hash.encode(), hashlib.sha256).hexdigest()[:32]


def stamp_matches(token_stamp: Optional[str], password_hash: str) -> bool:
    """Constant-time comparison; a token without a stamp never matches."""
    if not token_stamp:
        return False
    # Compare bytes: compare_digest raises on non-ASCII str, which must never turn into a 500.
    return hmac.compare_digest(token_stamp.encode(), password_stamp(password_hash).encode())


# ---- read-only AI token (Decision 7, B9) -------------------------------------------------
# For one chat request the backend gives the AI service a token of the requesting user that can
# only READ, through the normal endpoints and their scope checks (conditions 1, 2 and 4). It is a
# normal token plus `scp = "read"`, with a short lifetime and a mandatory password stamp. Tokens
# from login carry no `scp`. Any other `scp` value is rejected, so a future scope can never be
# mistaken for a full token by this code.
SCOPE_CLAIM = "scp"
READ_ONLY_SCOPE = "read"


@dataclass(frozen=True)
class TokenClaims:
    user_id: uuid.UUID
    password_stamp: Optional[str]
    scope: Optional[str] = None  # None = a normal (full) token; READ_ONLY_SCOPE = the AI token

    @property
    def read_only(self) -> bool:
        return self.scope == READ_ONLY_SCOPE


def create_access_token(user_id: uuid.UUID, password_hash: Optional[str] = None) -> Tuple[str, int]:
    """Returns (token, expires_in_seconds). The token carries the user id and, when the
    password hash is given (always, at login), the password stamp. Role and active status
    are re-read from the database on every request."""
    s = get_settings()
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=s.access_token_expire_minutes)
    claims = {"sub": str(user_id), "iat": now, "exp": exp}
    if password_hash is not None:
        claims[STAMP_CLAIM] = password_stamp(password_hash)
    token = jwt.encode(claims, s.jwt_secret_key.get_secret_value(), algorithm=s.jwt_algorithm)
    return token, s.access_token_expire_minutes * 60


def create_ai_token(user_id: uuid.UUID, password_hash: str) -> Tuple[str, int]:
    """The read-only token of `user_id` for the AI service (Decision 7). Returns (token,
    expires_in_seconds). The password stamp is mandatory: a password change or reset invalidates
    it like any other token, and deactivation does too (checked on every request)."""
    s = get_settings()
    now = datetime.now(timezone.utc)
    claims = {"sub": str(user_id), "iat": now, "exp": now + timedelta(minutes=s.ai_token_expire_minutes),
              STAMP_CLAIM: password_stamp(password_hash), SCOPE_CLAIM: READ_ONLY_SCOPE}
    token = jwt.encode(claims, s.jwt_secret_key.get_secret_value(), algorithm=s.jwt_algorithm)
    return token, s.ai_token_expire_minutes * 60


def decode_token(token: str) -> TokenClaims:
    s = get_settings()
    try:
        payload = jwt.decode(
            token,
            s.jwt_secret_key.get_secret_value(),
            algorithms=[s.jwt_algorithm],  # pinned: rejects alg=none and algorithm swaps
            options={"require": ["exp", "sub"]},
        )
        stamp = payload.get(STAMP_CLAIM)
        scope = payload.get(SCOPE_CLAIM)
        if scope is not None and scope != READ_ONLY_SCOPE:
            raise ValueError("unknown token scope")
        return TokenClaims(user_id=uuid.UUID(payload["sub"]), password_stamp=stamp if isinstance(stamp, str) else None,
                           scope=scope)
    except (jwt.PyJWTError, ValueError, KeyError, TypeError):
        raise UnauthorizedError("Invalid or expired token.")


def decode_access_token(token: str) -> uuid.UUID:
    """The user id only (signature and expiry checked). Kept for existing callers."""
    return decode_token(token).user_id
