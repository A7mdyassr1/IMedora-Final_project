import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.api.deps import Pagination, pagination_params, require_roles
from app.core.database import get_db
from app.core.roles import Role
from app.models.user import User
from app.schemas.common import Page
from app.schemas.user import PasswordResetRequest, UserCreate, UserResponse, UserUpdate
from app.services.user_service import UserService

# Administrators only; every query is scoped to the admin's own organization.
router = APIRouter(prefix="/users", tags=["users"])
AdminUser = Depends(require_roles(Role.ADMIN))


@router.post("", response_model=UserResponse, status_code=201, summary="Create a user")
def create_user(data: UserCreate, admin: User = AdminUser, db: Session = Depends(get_db)):
    return UserResponse.model_validate(UserService(db).create_user(admin.organization_id, data))


@router.get("", response_model=Page[UserResponse], summary="List users (paginated)")
def list_users(
    pagination: Pagination = Depends(pagination_params),
    role: Optional[Role] = None,
    is_active: Optional[bool] = None,
    hospital_id: Optional[uuid.UUID] = None,
    q: Optional[str] = Query(None, max_length=100, description="Search name or email"),
    admin: User = AdminUser,
    db: Session = Depends(get_db),
):
    items, total = UserService(db).list_users(
        admin.organization_id,
        pagination.page,
        pagination.page_size,
        role=role.value if role else None,
        is_active=is_active,
        hospital_id=hospital_id,
        q=q,
    )
    return Page[UserResponse](
        items=[UserResponse.model_validate(u) for u in items],
        total=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.get("/{user_id}", response_model=UserResponse, summary="Get a user")
def get_user(user_id: uuid.UUID, admin: User = AdminUser, db: Session = Depends(get_db)):
    return UserResponse.model_validate(UserService(db).get_user(admin.organization_id, user_id))


@router.patch("/{user_id}", response_model=UserResponse, summary="Update a user (also deactivates/reactivates)")
def update_user(user_id: uuid.UUID, data: UserUpdate, admin: User = AdminUser, db: Session = Depends(get_db)):
    return UserResponse.model_validate(UserService(db).update_user(admin.organization_id, admin, user_id, data))


@router.post("/{user_id}/reset-password", status_code=204, summary="Set a new password for a user")
def reset_password(user_id: uuid.UUID, body: PasswordResetRequest, admin: User = AdminUser, db: Session = Depends(get_db)):
    UserService(db).reset_password(admin.organization_id, admin, user_id, body.new_password)
    return Response(status_code=204)
