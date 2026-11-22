"""AuditService rules that need NO database (B3.1 CP2): what is captured, what is never stored,
and that the service only stages rows in the caller's session (never commits on its own)."""
import uuid
from datetime import date, datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.core.enums import AuditAction, DeviceStatus
from app.models import AuditLog, Device, User
from app.services.audit_service import PASSWORD_CHANGED, AuditService, snapshot


def _user(**kw) -> User:
    base = dict(id=uuid.uuid4(), organization_id=uuid.uuid4(), hospital_id=uuid.uuid4(), role_id=uuid.uuid4(),
                full_name="Nurse Joy", email="joy@h.test", password_hash="$argon2id$v=19$m=65536,t=3,p=4$secret",
                is_active=True, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    base.update(kw)
    return User(**base)


def test_snapshot_never_contains_password_hash_or_timestamps():
    snap = snapshot(_user())
    assert "password_hash" not in snap
    assert "created_at" not in snap and "updated_at" not in snap
    assert snap["email"] == "joy@h.test" and snap["is_active"] is True
    assert "$argon2" not in repr(snap)


def test_snapshot_values_are_json_safe():
    d = Device(id=uuid.uuid4(), organization_id=uuid.uuid4(), hospital_id=uuid.uuid4(), department_id=uuid.uuid4(),
               device_model_id=uuid.uuid4(), device_code="DEV-1", name="Vent", qr_identifier="QR-1",
               status=DeviceStatus.ACTIVE, installation_date=date(2024, 1, 2))
    snap = snapshot(d)
    assert isinstance(snap["id"], str) and snap["status"] == "active" and snap["installation_date"] == "2024-01-02"


def _service():
    db = MagicMock()
    return AuditService(db), db


def test_record_only_stages_the_row_in_the_callers_session():
    svc, db = _service()
    row = svc.record(actor_id=None, organization_id=uuid.uuid4(), table_name="users", record_id=uuid.uuid4(),
                     action=AuditAction.INSERT, new_values={"a": 1})
    db.add.assert_called_once_with(row)
    db.commit.assert_not_called()
    db.flush.assert_not_called()


def test_record_strips_any_secret_looking_key_but_keeps_the_password_marker():
    svc, _ = _service()
    row = svc.record(actor_id=None, organization_id=uuid.uuid4(), table_name="users", record_id=uuid.uuid4(),
                     action=AuditAction.UPDATE,
                     old_values={"password_hash": "x", "api_token": "t", "full_name": "A"},
                     new_values={"password": "p", "client_secret": "s", "full_name": "B", **PASSWORD_CHANGED})
    assert row.old_values == {"full_name": "A"}
    assert row.new_values == {"full_name": "B", "password_changed": True}


def test_updated_stores_only_changed_fields():
    svc, _ = _service()
    u = _user()
    before = snapshot(u)
    u.full_name = "Nurse Jenny"
    row = svc.updated(None, u, before)
    assert row.action == AuditAction.UPDATE
    assert row.old_values == {"full_name": "Nurse Joy"} and row.new_values == {"full_name": "Nurse Jenny"}
    assert row.organization_id == u.organization_id and row.record_id == u.id and row.table_name == "users"


def test_updated_writes_nothing_when_nothing_changed():
    svc, db = _service()
    u = _user()
    assert svc.updated(None, u, snapshot(u)) is None
    db.add.assert_not_called()


def test_password_change_is_recorded_as_a_marker_only():
    svc, _ = _service()
    u = _user()
    before = snapshot(u)
    u.password_hash = "$argon2id$v=19$new-hash"
    row = svc.updated(u.id, u, before, extra_new=dict(PASSWORD_CHANGED))
    assert row.old_values is None and row.new_values == {"password_changed": True}
    assert "argon2" not in repr(row.new_values)


def test_deleted_keeps_the_full_old_row_and_inserted_the_full_new_row():
    svc, _ = _service()
    u = _user()
    assert svc.deleted(None, u).old_values["email"] == "joy@h.test"
    ins = svc.inserted(None, u)
    assert ins.action == AuditAction.INSERT and ins.new_values["full_name"] == "Nurse Joy" and ins.old_values is None


def test_rows_without_an_organization_are_refused():
    svc, _ = _service()
    from app.models import DeviceCategory
    with pytest.raises(ValueError):
        svc.inserted(None, DeviceCategory(id=uuid.uuid4(), name="X"))  # global row: caller must pass the org


def test_audit_action_enum_matches_the_database_enum():
    assert [a.value for a in AuditAction] == ["insert", "update", "delete"]
    assert AuditLog.__table__.c.action.type.enums == ["insert", "update", "delete"]
