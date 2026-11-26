"""B6 CP4 - device history without a database: entry types per role, `types` parsing, and the
role-first 403 for department users asking for entries they may not see (no lookup happens)."""
import uuid

import pytest

from app.core.access import AccessScope, DeviceAccess
from app.core.exceptions import ForbiddenError
from app.core.roles import Role
from app.repositories.history_repository import ENTRY_TYPES
from app.services.device_history import DeviceHistoryService, HistoryTypesError, parse_types, visible_types


class _NoDatabase:
    def __getattr__(self, name):
        raise AssertionError(f"the database was used ({name}) before the role check")


def _scope(role: Role) -> AccessScope:
    access = {Role.ADMIN: DeviceAccess.ORGANIZATION, Role.DEPARTMENT_USER: DeviceAccess.DEPARTMENT}.get(role, DeviceAccess.HOSPITAL)
    return AccessScope(uuid.uuid4(), role, uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), access)


def test_entry_types_per_role():
    for role in (Role.ADMIN, Role.BIOMEDICAL_ENGINEER, Role.TECHNICIAN):
        assert visible_types(_scope(role)) == frozenset(ENTRY_TYPES)
    assert visible_types(_scope(Role.DEPARTMENT_USER)) == {"ticket_reported", "ticket_resolved"}


def test_types_parsing():
    assert parse_types(None) is None
    assert parse_types(" risk_assessment , qa_record ") == {"risk_assessment", "qa_record"}
    for bad in ("", ",", "audit", "qa_record,audit"):
        with pytest.raises(HistoryTypesError) as exc:
            parse_types(bad)
        assert (exc.value.status_code, exc.value.code) == (422, "validation_error")


@pytest.mark.parametrize("types", [{"risk_assessment"}, {"qa_record"}, {"maintenance_record"},
                                   {"ticket_reported", "risk_assessment"}])
def test_department_users_asking_for_other_types_get_403_before_any_lookup(types):
    with pytest.raises(ForbiddenError):
        DeviceHistoryService(_NoDatabase()).history(_scope(Role.DEPARTMENT_USER), uuid.uuid4(), frozenset(types),
                                                    None, None, 1, 20)


def test_snapshot_read_refuses_unsaved_changes():
    """B6-L3: start_snapshot_read() ends the current transaction, so it must never drop pending writes."""
    import pytest
    from sqlalchemy.orm import Session

    from app.core.database import start_snapshot_read
    from app.models.notification import Notification

    db = Session()
    db.add(Notification(title="x", notification_type="other"))
    with pytest.raises(RuntimeError, match="unsaved changes"):
        start_snapshot_read(db)
