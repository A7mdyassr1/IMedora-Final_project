import logging
from dataclasses import dataclass

from fastapi import Depends, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.roles import Role
from app.models.user import User
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)

# auto_error=False: we raise our own 401 so the body matches every other error.
bearer_scheme = HTTPBearer(auto_error=False, description="Paste the access_token from POST /api/v1/auth/login")

# Methods a read-only token may use (Decision 7, condition 4). Everything else changes data.
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class ReadOnlyTokenError(ForbiddenError):
    code = "read_only_token"
    default_message = "This token can only read data."


def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise UnauthorizedError("Authentication required.")
    # Signature, expiry, password stamp, and user/organization/hospital active status:
    # all checked on every request (AuthService.authenticate). A token that fails them is 401
    # whatever its scope; only a valid read-only token reaches the method check below.
    user, claims = AuthService(db).authenticate(credentials.credentials)
    # Decision 7, condition 4: the AI service's read-only token cannot change anything. Checked here,
    # in the one dependency every signed-in endpoint uses, before any endpoint code runs.
    if claims.read_only and request.method not in READ_METHODS:
        logger.warning("Read-only token refused for %s %s user_id=%s", request.method, request.url.path, user.id)
        raise ReadOnlyTokenError()
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
