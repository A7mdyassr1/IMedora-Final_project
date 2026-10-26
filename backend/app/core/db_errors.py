"""
Translates PostgreSQL constraint violations into clear API errors.

The database already enforces these rules (unique codes, warranty dates,
RESTRICT foreign keys). The backend does NOT re-implement them; it lets the
database decide and only maps the constraint NAME to a human message here.
Unknown constraints fall back to a generic message - raw SQL text never reaches clients.
"""
from typing import Tuple

from sqlalchemy.exc import IntegrityError

CONSTRAINT_MESSAGES = {
    # unique
    "uq_device_hospital_code": "A device with this code already exists in this hospital.",
    "devices_qr_identifier_key": "This QR identifier is already assigned to another device.",
    "uq_hospital_org_code": "A hospital with this code already exists.",
    "uq_department_hospital_name": "A department with this name already exists in this hospital.",
    "device_categories_name_key": "A device category with this name already exists.",
    "manufacturers_name_key": "A manufacturer with this name already exists.",
    "uq_device_model_manufacturer_name": "This manufacturer already has a model with this name.",
    "users_email_key": "A user with this email already exists.",
    # check
    "ck_device_warranty_after_installation": "Warranty expiry cannot be before the installation date.",
    # restrict foreign keys (delete blocked because something still points at the row)
    "devices_department_id_fkey": "This department still has devices assigned to it.",
    "devices_device_model_id_fkey": "This model is still used by devices.",
    "device_models_manufacturer_id_fkey": "This manufacturer still has device models.",
    "device_models_device_category_id_fkey": "This category still has device models.",
}


def describe_integrity_error(exc: IntegrityError) -> Tuple[int, str, str]:
    """Returns (http_status, error_code, message)."""
    orig = exc.orig
    pgcode = getattr(orig, "pgcode", None)
    constraint = getattr(getattr(orig, "diag", None), "constraint_name", None)
    known = CONSTRAINT_MESSAGES.get(constraint)

    if pgcode == "23514":  # check_violation
        return 422, "constraint_violation", known or "A value violates a data rule."
    if pgcode == "23505":  # unique_violation
        return 409, "conflict", known or "A record with the same unique value already exists."
    if pgcode == "23503":  # foreign_key_violation
        return 409, "in_use", known or "This record is linked to other data."
    return 409, "conflict", known or "The request conflicts with existing data."
