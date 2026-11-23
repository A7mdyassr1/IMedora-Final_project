"""B4 CP3 - database-free tests: maintenance request schemas, the overdue flag, the work-date rules,
and the ticket timeline v3 (work performed events, privacy)."""
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.enums import TicketStatus as S
from app.core.exceptions import BadRequestError
from app.schemas.maintenance import (
    MAX_FREQUENCY_DAYS, RECORD_DESCRIPTION_MAX, MaintenanceRecordCreate, MaintenanceRecordUpdate,
    MaintenanceScheduleCreate, MaintenanceScheduleResponse, MaintenanceScheduleUpdate, MaintenanceTypeCreate,
)
from app.services.maintenance_service import MaintenanceService
from app.services.ticket_timeline import AssignmentEntry, AuditEntry, Person, WorkEntry, build_timeline


# ---- schemas ----------------------------------------------------------------------------------------
def test_type_names_are_trimmed_and_lower_cased():
    assert MaintenanceTypeCreate(name="  Calibration ").name == "calibration"
    for bad in ("", "   ", "x" * 51):
        with pytest.raises(ValidationError):
            MaintenanceTypeCreate(name=bad)
    with pytest.raises(ValidationError):
        MaintenanceTypeCreate(name="ok", id=str(uuid.uuid4()))


def _record(**over):
    return {"device_id": str(uuid.uuid4()), "maintenance_type_id": str(uuid.uuid4()), "description": "Replaced fuse", **over}


def test_record_create_validation():
    r = MaintenanceRecordCreate(**_record(description="  Replaced fuse \n"))
    assert r.description == "Replaced fuse" and r.performed_at is None and r.ticket_id is None and r.schedule_id is None
    assert len(MaintenanceRecordCreate(**_record(description="x" * RECORD_DESCRIPTION_MAX)).description) == RECORD_DESCRIPTION_MAX
    for over in ({"description": ""}, {"description": "  "}, {"description": "x" * (RECORD_DESCRIPTION_MAX + 1)},
                 {"performed_by": str(uuid.uuid4())}, {"hospital_id": str(uuid.uuid4())}, {"organization_id": str(uuid.uuid4())},
                 {"ticket_id": "nope"}, {"performed_at": "yesterday"}):
        with pytest.raises(ValidationError):
            MaintenanceRecordCreate(**_record(**over))


def test_record_update_needs_a_change_and_rejects_history_fields():
    assert MaintenanceRecordUpdate(description=" fixed ").description == "fixed"
    for body in ({}, {"description": None}, {"device_id": str(uuid.uuid4())}, {"schedule_id": str(uuid.uuid4())},
                 {"performed_by": str(uuid.uuid4())}, {"description": ""}):
        with pytest.raises(ValidationError):
            MaintenanceRecordUpdate(**body)


def test_schedule_create_and_update_validation():
    base = {"device_id": str(uuid.uuid4()), "maintenance_type_id": str(uuid.uuid4()), "next_due_date": "2027-01-01"}
    assert MaintenanceScheduleCreate(**base, frequency_days=1).frequency_days == 1
    assert MaintenanceScheduleCreate(**base, frequency_days=MAX_FREQUENCY_DAYS).frequency_days == MAX_FREQUENCY_DAYS
    for freq in (0, -5, MAX_FREQUENCY_DAYS + 1, "often"):
        with pytest.raises(ValidationError):
            MaintenanceScheduleCreate(**base, frequency_days=freq)
    with pytest.raises(ValidationError):
        MaintenanceScheduleCreate(**base, frequency_days=30, last_performed_date="2026-01-01")  # server-owned
    assert MaintenanceScheduleUpdate(is_active=False).model_fields_set == {"is_active"}
    for body in ({}, {"is_active": None}, {"next_due_date": None}, {"frequency_days": 0}, {"device_id": str(uuid.uuid4())}):
        with pytest.raises(ValidationError):
            MaintenanceScheduleUpdate(**body)


def test_overdue_flag_is_for_active_schedules_due_before_today():
    today = date(2026, 11, 23)
    dev = SimpleNamespace(id=uuid.uuid4(), device_code="D", name="N", department_id=uuid.uuid4(),
                          department=SimpleNamespace(name="ICU"), deleted_at=None)
    def sched(due, active=True):
        return SimpleNamespace(id=uuid.uuid4(), device=dev, hospital_id=uuid.uuid4(),
                               maintenance_type=SimpleNamespace(id=uuid.uuid4(), name="preventive"), frequency_days=30,
                               next_due_date=due, last_performed_date=None, is_active=active,
                               created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    assert MaintenanceScheduleResponse.build(sched(date(2026, 11, 22)), today).is_overdue is True
    assert MaintenanceScheduleResponse.build(sched(today), today).is_overdue is False          # due today: not overdue
    assert MaintenanceScheduleResponse.build(sched(date(2026, 1, 1), active=False), today).is_overdue is False


# ---- work date rules ----------------------------------------------------------------------------------
def test_work_date_cannot_be_in_the_future_or_before_the_ticket():
    service = MaintenanceService.__new__(MaintenanceService)  # the rule needs no database
    now = datetime.now(timezone.utc)
    assert service._check_work_time(None) is None
    assert service._check_work_time(now - timedelta(days=3)) == now - timedelta(days=3)
    assert service._check_work_time(now + timedelta(minutes=2)) is not None          # clock tolerance
    naive = (now - timedelta(hours=1)).replace(tzinfo=None)
    assert service._check_work_time(naive).tzinfo is timezone.utc                    # naive = UTC
    with pytest.raises(BadRequestError):
        service._check_work_time(now + timedelta(hours=1))
    ticket = SimpleNamespace(created_at=now - timedelta(days=1))
    with pytest.raises(BadRequestError):
        service._check_work_time(now - timedelta(days=2), ticket)
    assert service._check_work_time(now - timedelta(hours=1), ticket) is not None


# ---- timeline v3 -----------------------------------------------------------------------------------
T0 = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)
REP, TECH, ENG = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
PEOPLE = {REP: Person(REP, "Nora Nurse", "department_user"), TECH: Person(TECH, "Tarek Tech", "technician"),
          ENG: Person(ENG, "Eman Eng", "biomedical_engineer")}


def _at(m):
    return T0 + timedelta(minutes=m)


def _flow(viewer=ENG, names=True):
    audit = [AuditEntry(T0, "insert", REP, None, {"status": "open"}),
             AuditEntry(_at(5), "update", ENG, {"status": "open"}, {"status": "assigned"}),
             AuditEntry(_at(10), "update", TECH, {"status": "assigned"}, {"status": "in_progress"}),
             AuditEntry(_at(40), "update", TECH, {"status": "in_progress"}, {"status": "resolved"})]
    return build_timeline(ticket_created_at=T0, reporter_id=REP, audit=audit, people=PEOPLE, viewer_id=viewer,
                          viewer_sees_names=names, assignments=[AssignmentEntry(TECH, _at(5), assigned_by=ENG)],
                          work=[WorkEntry(_at(30), TECH, "Replaced the power supply")])


def test_work_performed_appears_in_order_with_the_running_status():
    items = _flow()
    assert [(i.kind, i.status) for i in items] == [
        ("created", S.OPEN), ("assigned", S.ASSIGNED), ("status_changed", S.IN_PROGRESS),
        ("work_performed", S.IN_PROGRESS), ("status_changed", S.RESOLVED)]
    assert items[3].message == "Work performed: Replaced the power supply" and items[3].actor == "Tarek Tech"


def test_department_user_sees_the_work_description_but_not_the_name():
    item = _flow(viewer=REP, names=False)[3]
    assert item.message == "Work performed: Replaced the power supply" and item.actor == "Technician"


def test_work_and_resolution_at_the_same_instant_show_the_work_first():
    audit = [AuditEntry(T0, "insert", REP, None, {"status": "open"}),
             AuditEntry(_at(9), "update", TECH, {"status": "in_progress"}, {"status": "resolved"})]
    items = build_timeline(ticket_created_at=T0, reporter_id=REP, audit=audit, people=PEOPLE, viewer_id=ENG,
                           viewer_sees_names=True, work=[WorkEntry(_at(9), TECH, "Fixed")])
    assert [i.kind for i in items] == ["created", "work_performed", "status_changed"]
