import logging
import uuid
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.roles import Role
from app.core.security import hash_password
from app.models.user import User
from app.repositories.hospital_repository import HospitalRepository
from app.repositories.role_repository import RoleRepository
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserCreate, UserUpdate

logger = logging.getLogger(__name__)


class UserService:
    """User administration. Every operation is scoped to ONE organization, so an
    admin of one organization can never see or change another's users."""

    def __init__(self, db: Session):
        self.db = db
        self.users = UserRepository(db)
        self.roles = RoleRepository(db)
        self.hospitals = HospitalRepository(db)

    # -- helpers --------------------------------------------------------------
    def _get_in_org(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> User:
        user = self.users.get_by_id(user_id, organization_id)
        if user is None or user.deleted_at is not None:
            raise NotFoundError("User not found.")
        return user

    def _role_id(self, role: Role) -> uuid.UUID:
        row = self.roles.get_by_name(role.value)
        if row is None:
            raise BadRequestError(f"Role '{role.value}' is not configured in this database.")
        return row.id

    def _validate_placement(self, organization_id, hospital_id, department_id) -> None:
        if self.hospitals.get_in_organization(organization_id, hospital_id) is None:
            raise BadRequestError("Hospital does not exist in your organization.")
        if department_id is not None and self.hospitals.get_department_in_hospital(hospital_id, department_id) is None:
            raise BadRequestError("Department does not belong to the selected hospital.")

    # -- operations -------------------------------------------------------------
    def create_user(self, organization_id: uuid.UUID, data: UserCreate) -> User:
        if self.users.get_by_email(data.email):
            raise ConflictError("A user with this email already exists.")
        role_id = self._role_id(data.role)
        self._validate_placement(organization_id, data.hospital_id, data.department_id)

        user = self.users.add(
            User(
                organization_id=organization_id,
                hospital_id=data.hospital_id,
                department_id=data.department_id,
                role_id=role_id,
                full_name=data.full_name,
                email=data.email,
                password_hash=hash_password(data.password),
                is_active=True,
            )
        )
        self.db.commit()
        logger.info("User created user_id=%s role=%s", user.id, data.role.value)
        return self.users.get_by_id(user.id)  # reload with role/hospital/department

    def get_user(self, organization_id: uuid.UUID, user_id: uuid.UUID) -> User:
        return self._get_in_org(organization_id, user_id)

    def list_users(self, organization_id: uuid.UUID, page: int, page_size: int, **filters) -> Tuple[List[User], int]:
        return self.users.list_page(organization_id, page, page_size, **filters)

    def update_user(self, organization_id: uuid.UUID, acting: User, user_id: uuid.UUID, data: UserUpdate) -> User:
        user = self._get_in_org(organization_id, user_id)
        changes = data.model_dump(exclude_unset=True)

        if user.id == acting.id:  # lock-out protection
            if changes.get("is_active") is False:
                raise BadRequestError("You cannot deactivate your own account.")
            if "role" in changes and changes["role"] != Role.ADMIN:
                raise BadRequestError("You cannot remove your own admin role.")

        if "email" in changes and changes["email"] != user.email.lower():
            if self.users.get_by_email(changes["email"]):
                raise ConflictError("A user with this email already exists.")
            user.email = changes["email"]
        if "full_name" in changes:
            user.full_name = changes["full_name"].strip()
        if "role" in changes:
            user.role_id = self._role_id(changes["role"])
        if "is_active" in changes:
            user.is_active = changes["is_active"]
        if "hospital_id" in changes or "department_id" in changes:
            hospital_id = changes.get("hospital_id", user.hospital_id)
            department_id = changes.get("department_id", user.department_id)
            self._validate_placement(organization_id, hospital_id, department_id)
            user.hospital_id, user.department_id = hospital_id, department_id

        self.db.commit()
        logger.info("User updated user_id=%s fields=%s by=%s", user.id, sorted(changes), acting.id)
        return self.users.get_by_id(user.id)

    def reset_password(self, organization_id: uuid.UUID, acting: User, user_id: uuid.UUID, new_password: str) -> None:
        user = self._get_in_org(organization_id, user_id)
        user.password_hash = hash_password(new_password)
        self.db.commit()
        logger.info("Password reset user_id=%s by=%s", user.id, acting.id)
