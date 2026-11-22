import logging
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestError, UnauthorizedError
from app.core.security import create_access_token, decode_token, dummy_hash, hash_password, stamp_matches, verify_password
from app.models.user import User
from app.repositories.hospital_repository import HospitalRepository
from app.repositories.user_repository import UserRepository
from app.services.audit_service import PASSWORD_CHANGED, AuditService, snapshot

logger = logging.getLogger(__name__)

_BAD_LOGIN = "Invalid email or password."
_BAD_TOKEN = "Invalid or expired token."


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.users = UserRepository(db)
        self.structure = HospitalRepository(db)

    def account_block_reason(self, user: User) -> Optional[str]:
        """Why this account may not be used right now, or None. One rule for login AND every
        request: the user, their organization and their hospital must all be active (Decision 6)."""
        if not user.is_active or user.deleted_at is not None:
            return "user inactive"
        org = self.structure.get_organization(user.organization_id)
        if org is None or not org.is_active:
            return "organization inactive"
        if user.hospital is None or not user.hospital.is_active:
            return "hospital inactive"
        return None

    def login(self, identifier: str, password: str) -> Tuple[User, str, int]:
        user = self.users.get_by_email(identifier)
        password_ok = verify_password(password, user.password_hash if user else dummy_hash())

        if user is None or not password_ok:
            # Unknown identifiers are not logged: people sometimes paste a password into this field.
            logger.warning("Failed login (%s)", f"user_id={user.id}" if user else "unknown identifier")
            raise UnauthorizedError(_BAD_LOGIN)
        reason = self.account_block_reason(user)
        if reason is not None:
            logger.warning("Login refused (%s) user_id=%s", reason, user.id)
            raise UnauthorizedError(_BAD_LOGIN)  # same message: don't reveal account state

        token, expires_in = create_access_token(user.id, user.password_hash)
        logger.info("User logged in user_id=%s", user.id)
        return user, token, expires_in

    def user_for_token(self, token: str) -> User:
        """Every authenticated request: valid signature and expiry, the user still exists, the
        account is usable (user, organization, hospital active) and the password is unchanged
        since the token was issued (password stamp). Any failure is the same 401."""
        claims = decode_token(token)
        # Re-read on every request so deactivation / role changes take effect immediately.
        user = self.users.get_by_id(claims.user_id)
        if user is None:
            raise UnauthorizedError(_BAD_TOKEN)
        reason = self.account_block_reason(user)
        if reason is None and not stamp_matches(claims.password_stamp, user.password_hash):
            reason = "password changed since the token was issued, or token has no stamp"
        if reason is not None:
            logger.info("Token rejected (%s) user_id=%s", reason, user.id)
            raise UnauthorizedError(_BAD_TOKEN)
        return user

    def change_password(self, user: User, current_password: str, new_password: str) -> None:
        if not verify_password(current_password, user.password_hash):
            raise BadRequestError("Current password is incorrect.")
        if verify_password(new_password, user.password_hash):
            raise BadRequestError("New password must be different from the current one.")
        user.password_hash = hash_password(new_password)  # every earlier token stops working (password stamp)
        AuditService(self.db).updated(user.id, user, snapshot(user), extra_new=dict(PASSWORD_CHANGED))
        self.db.commit()
        logger.info("Password changed user_id=%s", user.id)
