"""
Create (or reset the password of) a user - the way to get the FIRST admin into
the database, and to give the dev-seed users (which have a placeholder hash) a
real password.

Run from backend/:
    python -m scripts.create_user --email admin@cairomed.example --full-name "Admin" \\
        --role admin --organization-code CAIRO-MED --hospital-code CMC-MAIN
    python -m scripts.create_user --email mostafa.tech@cairomed.example --reset-password \\
        --organization-code CAIRO-MED

The password is read from a hidden prompt (or IMEDORA_USER_PASSWORD for automation),
never from a command-line argument, so it can't end up in shell history.
"""
import argparse
import getpass
import os
import sys

from sqlalchemy import select

from app.core.database import get_session_factory
from app.core.roles import Role
from app.core.security import hash_password
from app.models.department import Department
from app.models.hospital import Hospital
from app.models.organization import Organization
from app.repositories.role_repository import RoleRepository
from app.repositories.user_repository import UserRepository
from app.schemas.user import MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH, UserCreate
from app.services.user_service import UserService


def read_password() -> str:
    pw = os.environ.get("IMEDORA_USER_PASSWORD")
    if pw is None:
        pw = getpass.getpass("Password: ")
        if pw != getpass.getpass("Repeat password: "):
            sys.exit("Passwords do not match.")
    if not MIN_PASSWORD_LENGTH <= len(pw) <= MAX_PASSWORD_LENGTH:
        sys.exit(f"Password must be {MIN_PASSWORD_LENGTH}-{MAX_PASSWORD_LENGTH} characters.")
    return pw


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--email", required=True)
    p.add_argument("--organization-code", required=True)
    p.add_argument("--full-name")
    p.add_argument("--role", choices=[r.value for r in Role], default=Role.ADMIN.value)
    p.add_argument("--hospital-code")
    p.add_argument("--department", help="Department name within the hospital (optional)")
    p.add_argument("--reset-password", action="store_true", help="Set a new password for an EXISTING user")
    args = p.parse_args()

    with get_session_factory()() as db:
        org = db.scalars(select(Organization).where(Organization.code == args.organization_code)).first()
        if org is None:
            sys.exit(f"No organization with code '{args.organization_code}'.")

        users = UserRepository(db)
        existing = users.get_by_email(args.email)

        if args.reset_password:
            if existing is None or existing.organization_id != org.id:
                sys.exit("No such user in that organization.")
            existing.password_hash = hash_password(read_password())
            db.commit()
            print(f"Password updated for {existing.email}.")
            return

        if existing is not None:
            sys.exit("A user with that email already exists (use --reset-password to change the password).")
        if not (args.full_name and args.hospital_code):
            sys.exit("--full-name and --hospital-code are required when creating a user.")

        hospital = db.scalars(
            select(Hospital).where(Hospital.organization_id == org.id, Hospital.code == args.hospital_code)
        ).first()
        if hospital is None:
            sys.exit(f"No hospital '{args.hospital_code}' in organization '{org.code}'.")

        department_id = None
        if args.department:
            dept = db.scalars(
                select(Department).where(Department.hospital_id == hospital.id, Department.name == args.department)
            ).first()
            if dept is None:
                sys.exit(f"No department '{args.department}' in that hospital.")
            department_id = dept.id

        RoleRepository(db).ensure_standard_roles()
        db.commit()
        user = UserService(db).create_user(
            org.id,
            UserCreate(
                email=args.email,
                full_name=args.full_name,
                password=read_password(),
                role=Role(args.role),
                hospital_id=hospital.id,
                department_id=department_id,
            ),
        )
        print(f"Created {user.role_name} {user.email} ({user.id}).")


if __name__ == "__main__":
    main()
