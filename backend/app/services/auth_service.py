import logging
from typing import Tuple

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestError, UnauthorizedError
from app.core.security import create_access_token, dummy_hash, hash_password, verify_password
from app.models.user import User
from app.repositories.user_repository import UserRepository

logger = logging.getLogger(__name__)

_BAD_LOGIN = "Invalid email or password."


class AuthService:
    def __init__(self, db: Session):
        self.db = db
        self.users = UserRepository(db)

    def login(self, identifier: str, password: str) -> Tuple[User, str, int]:
        user = self.users.get_by_email(identifier)
        password_ok = verify_password(password, user.password_hash if user else dummy_hash())

        if user is None or not password_ok:
            # Unknown identifiers are not logged: people sometimes paste a password into this field.
            logger.warning("Failed login (%s)", f"user_id={user.id}" if user else "unknown identifier")
            raise UnauthorizedError(_BAD_LOGIN)
        if not user.is_active or user.deleted_at is not None:
            logger.warning("Login refused for inactive user_id=%s", user.id)
            raise UnauthorizedError(_BAD_LOGIN)  # same message: don't reveal account state

        token, expires_in = create_access_token(user.id)
        logger.info("User logged in user_id=%s", user.id)
        return user, token, expires_in

    def change_password(self, user: User, current_password: str, new_password: str) -> None:
        if not verify_password(current_password, user.password_hash):
            raise BadRequestError("Current password is incorrect.")
        if verify_password(new_password, user.password_hash):
            raise BadRequestError("New password must be different from the current one.")
        user.password_hash = hash_password(new_password)
        self.db.commit()
        logger.info("Password changed user_id=%s", user.id)
