from dataclasses import dataclass

from fastapi import Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.roles import Role
from app.core.security import decode_access_token
from app.models.user import User
from app.repositories.user_repository import UserRepository

# auto_error=False: we raise our own 401 so the body matches every other error.
bearer_scheme = HTTPBearer(auto_error=False, description="Paste the access_token from POST /api/v1/auth/login")


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise UnauthorizedError("Authentication required.")
    user_id = decode_access_token(credentials.credentials)
    # Re-read on every request so deactivation / role changes take effect immediately.
    user = UserRepository(db).get_by_id(user_id)
    if user is None or not user.is_active or user.deleted_at is not None:
        raise UnauthorizedError("Invalid or expired token.")
    return user


def require_roles(*roles: Role):
    """Dependency factory: `Depends(require_roles(Role.ADMIN, Role.BIOMEDICAL_ENGINEER))`."""
    allowed = {r.value for r in roles}

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role.name not in allowed:
            raise ForbiddenError()
        return user

    return dependency


@dataclass
class Pagination:
    page: int
    page_size: int


def pagination_params(page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100)) -> Pagination:
    return Pagination(page=page, page_size=page_size)


# ---- reusable authorization levels -------------------------------------------------
# Read access: any authenticated user (always organization-scoped).
# Structure (hospitals/departments/locations): administrators.
# Catalog and devices: administrators + biomedical engineers.
CurrentUser = Depends(get_current_user)
AdminOnly = Depends(require_roles(Role.ADMIN))
CanManageAssets = Depends(require_roles(Role.ADMIN, Role.BIOMEDICAL_ENGINEER))
