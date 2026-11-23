"""
Translates PostgreSQL constraint violations into clear API errors.

The database already enforces these rules (unique codes, warranty dates,
RESTRICT foreign keys). The backend does NOT re-implement them; it lets the
database decide and only maps the constraint NAME to a human message here.
Unknown constraints fall back to a generic message - raw SQL text never reaches clients.
"""
from typing import Optional, Tuple

from sqlalchemy.exc import DBAPIError, IntegrityError

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
    "uq_active_assignment": "This user is already assigned to this ticket.",
    "uq_schedule_device_type": "This device already has a schedule for this maintenance type.",
    "maintenance_types_name_key": "A maintenance type with this name already exists.",
    "parts_part_number_key": "A part with this part number already exists.",
    "uq_inventory_hospital_part": "This hospital already has a stock record for this part.",
    "uq_record_part": "This part is already listed on this maintenance record; change its quantity instead.",
    # check
    "ck_device_warranty_after_installation": "Warranty expiry cannot be before the installation date.",
    "ck_ticket_resolved_status_has_timestamp": "A resolved or closed ticket must have a resolution time.",
    "ck_ticket_resolved_after_created": "A ticket cannot be resolved before it was created.",
    "ck_assignment_unassigned_after_assigned": "An assignment cannot end before it started.",
    "ck_schedule_frequency_positive": "The maintenance frequency must be at least one day.",
    "ck_inventory_reorder_non_negative": "The reorder threshold cannot be negative.",
    "ck_maintenance_parts_quantity_positive": "The quantity of a used part must be at least one.",
    # composite foreign keys of maintenance records (B4 CP3; the service checks these first)
    "fk_record_ticket_same_device": "The ticket belongs to another device.",
    "fk_record_schedule_same_device_and_type": "The schedule belongs to another device or maintenance type.",
    # restrict foreign keys (delete blocked because something still points at the row)
    "devices_department_id_fkey": "This department still has devices assigned to it.",
    "devices_device_model_id_fkey": "This model is still used by devices.",
    "device_models_manufacturer_id_fkey": "This manufacturer still has device models.",
    "device_models_device_category_id_fkey": "This category still has device models.",
    "part_inventory_part_id_fkey": "This part is still stocked by a hospital.",
    "maintenance_parts_part_id_fkey": "This part has been used in maintenance records.",
    "attachments_ticket_id_fkey": "This ticket still has attachments.",
}

# CHECK violations that are a CONFLICT with the current data, not an invalid request (B5).
# The services check stock first under a row lock; these are the last line of defence.
CONFLICT_CHECKS = {
    "ck_inventory_quantity_non_negative": ("insufficient_stock", "There is not enough stock of this part."),
}

# Errors raised by database triggers (RAISE EXCEPTION, SQLSTATE P0001), keyed by trigger function.
# The trigger's own text is never sent to clients.
TRIGGER_ERRORS = {
    "adjust_part_inventory_on_usage": (
        "part_not_stocked", "This part is not stocked at the device's hospital, so its use cannot be recorded."),
}


def describe_integrity_error(exc: IntegrityError) -> Tuple[int, str, str]:
    """Returns (http_status, error_code, message)."""
    orig = exc.orig
    pgcode = getattr(orig, "pgcode", None)
    constraint = getattr(getattr(orig, "diag", None), "constraint_name", None)
    known = CONSTRAINT_MESSAGES.get(constraint)

    if pgcode == "23514" and constraint in CONFLICT_CHECKS:
        code, message = CONFLICT_CHECKS[constraint]
        return 409, code, message
    if pgcode == "23514":  # check_violation
        return 422, "constraint_violation", known or "A value violates a data rule."
    if pgcode == "23505":  # unique_violation
        return 409, "conflict", known or "A record with the same unique value already exists."
    if pgcode == "23503":  # foreign_key_violation
        return 409, "in_use", known or "This record is linked to other data."
    return 409, "conflict", known or "The request conflicts with existing data."


def describe_trigger_error(exc: DBAPIError) -> Optional[Tuple[int, str, str]]:
    """(http_status, error_code, message) for a RAISE EXCEPTION (P0001) from a database trigger,
    or None when the error is something else (it then stays an internal error)."""
    orig = exc.orig
    if getattr(orig, "pgcode", None) != "P0001":
        return None
    context = getattr(getattr(orig, "diag", None), "context", None) or ""
    for function, (code, message) in TRIGGER_ERRORS.items():
        if function in context:
            return 409, code, message
    return 409, "conflict", "The change was rejected by a database rule."
