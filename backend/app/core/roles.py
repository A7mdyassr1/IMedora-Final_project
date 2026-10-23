from enum import StrEnum


class Role(StrEnum):
    """Values of the existing `roles.name` column. The database has no 'viewer' role;
    read-mostly hospital staff are `department_user`."""

    ADMIN = "admin"
    BIOMEDICAL_ENGINEER = "biomedical_engineer"
    TECHNICIAN = "technician"
    DEPARTMENT_USER = "department_user"
