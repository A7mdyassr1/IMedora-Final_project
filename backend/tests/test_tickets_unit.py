"""B4 CP1 - database-free tests: problem-category codec (parity with the mobile app), the
ticket request schema, the timeline builder, ticket visibility rules and the response builder."""
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from app.core.access import AccessScope, DepartmentRequiredError, DeviceAccess, TicketAccess
from app.core.enums import TicketPriority, TicketStatus
from app.core.roles import Role
from app.schemas.ticket import DESCRIPTION_MAX_LENGTH, TicketCreate, TicketResponse
from app.services.ticket_timeline import AuditEntry, Person, build_timeline
from app.utils.problem_category import ProblemCategory, compose, parse

MOBILE_LABELS = ["Device not working", "Abnormal reading", "Physical damage", "Alarm/problem", "Power issue", "Other"]


# ---- problem category codec ---------------------------------------------------------------------
def test_category_labels_are_exactly_the_mobile_labels():
    assert [c.value for c in ProblemCategory] == MOBILE_LABELS


@pytest.mark.parametrize("label", MOBILE_LABELS)
def test_compose_and_parse_round_trip_for_every_label(label):
    stored = compose(ProblemCategory(label), "  The device won't turn on \n")
    assert stored == f"[{label}] The device won't turn on"
    assert parse(stored) == (ProblemCategory(label), "The device won't turn on")


@pytest.mark.parametrize("stored, expected", [
    ("Abnormal pressure reading on the display.", (ProblemCategory.OTHER, "Abnormal pressure reading on the display.")),
    ("[Unknown thing] text", (ProblemCategory.OTHER, "[Unknown thing] text")),       # unknown label: whole text
    ("[power issue] lower case", (ProblemCategory.OTHER, "[power issue] lower case")),  # labels are exact
    ("[Power issue]no space", (ProblemCategory.POWER_ISSUE, "no space")),
    ("  [Alarm/problem]   beeps  ", (ProblemCategory.ALARM_PROBLEM, "beeps")),
    ("[Power issue] [Other] nested", (ProblemCategory.POWER_ISSUE, "[Other] nested")),  # first prefix only
    ("[Physical damage] line one\nline two", (ProblemCategory.PHYSICAL_DAMAGE, "line one\nline two")),
    ("[Other]", (ProblemCategory.OTHER, "")),
    ("", (ProblemCategory.OTHER, "")),
])
def test_parse_follows_the_mobile_rules(stored, expected):
    assert parse(stored) == expected


# ---- request schema ---------------------------------------------------------------------------------
def _body(**over):
    return {"device_id": str(uuid.uuid4()), "category": "Power issue", "description": "Won't start", **over}


def test_ticket_create_trims_and_defaults_priority_to_none():
    t = TicketCreate(**_body(description="  Won't start  "))
    assert t.description == "Won't start" and t.priority is None and t.category is ProblemCategory.POWER_ISSUE
    assert TicketCreate(**_body(priority=None)).priority is None        # mobile sends null
    assert TicketCreate(**_body(priority="critical")).priority is TicketPriority.CRITICAL


@pytest.mark.parametrize("over", [
    {"description": ""}, {"description": "   \n "}, {"description": "x" * (DESCRIPTION_MAX_LENGTH + 1)},
    {"category": "Broken"}, {"category": "power issue"}, {"priority": "urgent"}, {"device_id": "not-a-uuid"},
    {"status": "closed"}, {"reported_by": str(uuid.uuid4())}, {"hospital_id": str(uuid.uuid4())},
    {"organization_id": str(uuid.uuid4())},
])
def test_ticket_create_rejects_invalid_or_server_owned_fields(over):
    with pytest.raises(ValidationError):
        TicketCreate(**_body(**over))


def test_ticket_create_accepts_the_maximum_length():
    assert len(TicketCreate(**_body(description="x" * DESCRIPTION_MAX_LENGTH)).description) == DESCRIPTION_MAX_LENGTH


# ---- timeline -------------------------------------------------------------------------------------
T0 = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)
REPORTER, TECH, ENG = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
PEOPLE = {REPORTER: Person(REPORTER, "Nora Nurse", "department_user"),
          TECH: Person(TECH, "Tarek Tech", "technician"),
          ENG: Person(ENG, "Eman Eng", "biomedical_engineer")}


def _upd(minutes, user, new, old=None):
    return AuditEntry(T0 + timedelta(minutes=minutes), "update", user, old, new)


def _timeline(audit, viewer=ENG, names=True):
    return build_timeline(ticket_created_at=T0, reporter_id=REPORTER, audit=audit, people=PEOPLE,
                          viewer_id=viewer, viewer_sees_names=names)


def test_timeline_from_insert_and_update_rows():
    audit = [
        AuditEntry(T0, "insert", REPORTER, None, {"status": "open", "priority": "medium"}),
        _upd(5, ENG, {"priority": "high"}, {"priority": "medium"}),
        _upd(10, TECH, {"status": "in_progress"}, {"status": "assigned"}),
        _upd(20, TECH, {"status": "resolved", "resolved_at": "x"}, {"status": "in_progress", "resolved_at": None}),
    ]
    items = _timeline(audit)
    assert [(i.kind, i.status, i.message, i.actor) for i in items] == [
        ("created", TicketStatus.OPEN, "Ticket created.", "Nora Nurse"),
        ("priority_changed", TicketStatus.OPEN, "Priority changed from Medium to High.", "Eman Eng"),
        ("status_changed", TicketStatus.IN_PROGRESS, "Status changed to In Progress.", "Tarek Tech"),
        ("status_changed", TicketStatus.RESOLVED, "Status changed to Resolved.", "Tarek Tech"),
    ]


def test_timeline_without_insert_row_falls_back_to_created_at_and_reporter():
    # The seeded ticket: created by SQL (no INSERT audit row), later resolved.
    items = _timeline([_upd(60, TECH, {"status": "resolved"})])
    assert items[0].kind == "created" and items[0].at == T0 and items[0].actor == "Nora Nurse"
    assert items[0].status is TicketStatus.OPEN
    assert (items[1].kind, items[1].status) == ("status_changed", TicketStatus.RESOLVED)


def test_timeline_sorts_by_time_and_ignores_unrelated_rows():
    audit = [
        _upd(30, ENG, {"status": "closed"}),
        _upd(10, ENG, {"problem_description": "edited"}),       # not a timeline event
        AuditEntry(T0 + timedelta(minutes=40), "delete", ENG, {"status": "closed"}, None),
        AuditEntry(T0, "insert", REPORTER, None, {"status": "open"}),
        _upd(20, TECH, {"status": "resolved"}),
    ]
    assert [i.status for i in _timeline(audit)] == [TicketStatus.OPEN, TicketStatus.RESOLVED, TicketStatus.CLOSED]


def test_timeline_priority_without_old_value_and_soft_delete():
    items = _timeline([AuditEntry(T0, "insert", REPORTER, None, {"status": "open"}),
                       _upd(1, ENG, {"priority": "critical"}),
                       _upd(2, ENG, {"deleted_at": "2026-11-01T09:02:00+00:00"})])
    assert [i.message for i in items[1:]] == ["Priority changed to Critical.", "Ticket deleted."]


def test_department_viewer_sees_roles_not_names_except_their_own():
    audit = [AuditEntry(T0, "insert", REPORTER, None, {"status": "open"}),
             _upd(5, ENG, {"priority": "high"}), _upd(10, TECH, {"status": "in_progress"})]
    items = _timeline(audit, viewer=REPORTER, names=False)
    assert [i.actor for i in items] == ["Nora Nurse", "Biomedical engineer", "Technician"]


def test_unknown_actor_and_unknown_values_do_not_break_the_timeline():
    stranger = uuid.uuid4()
    items = _timeline([AuditEntry(T0, "insert", None, None, {"status": "weird"}), _upd(1, stranger, {"status": "bogus"})])
    assert items[0].actor is None and items[0].status is TicketStatus.OPEN
    assert items[1].actor is None and items[1].status is TicketStatus.OPEN and "bogus" in items[1].message


# ---- visibility rules -----------------------------------------------------------------------------
def _scope(role, department=True):
    access = {Role.ADMIN: DeviceAccess.ORGANIZATION, Role.BIOMEDICAL_ENGINEER: DeviceAccess.HOSPITAL,
              Role.TECHNICIAN: DeviceAccess.HOSPITAL}.get(role, DeviceAccess.DEPARTMENT if department else DeviceAccess.NONE)
    return AccessScope(uuid.uuid4(), role, uuid.uuid4(), uuid.uuid4(), uuid.uuid4() if department else None, access)


def test_ticket_access_per_role():
    assert _scope(Role.ADMIN).ticket_access is TicketAccess.ORGANIZATION
    assert _scope(Role.BIOMEDICAL_ENGINEER).ticket_access is TicketAccess.HOSPITAL
    assert _scope(Role.TECHNICIAN).ticket_access is TicketAccess.HOSPITAL
    assert _scope(Role.DEPARTMENT_USER).ticket_access is TicketAccess.OWN_REPORTS
    # Q11: losing the department does not remove read access to one's own reports
    assert _scope(Role.DEPARTMENT_USER, department=False).ticket_access is TicketAccess.OWN_REPORTS


def test_reporting_scope_is_hospital_wide_for_department_users_and_refused_without_department():
    s = _scope(Role.DEPARTMENT_USER)
    r = s.reporting_scope()
    assert r.device_access is DeviceAccess.HOSPITAL and r.device_department_id is None and r.user_id == s.user_id
    with pytest.raises(DepartmentRequiredError):
        _scope(Role.DEPARTMENT_USER, department=False).reporting_scope()
    assert _scope(Role.ADMIN).reporting_scope().device_hospital_id is None
    eng = _scope(Role.BIOMEDICAL_ENGINEER)
    assert eng.reporting_scope().device_hospital_id == eng.hospital_id


def test_only_department_users_see_staff_as_roles():
    assert not _scope(Role.DEPARTMENT_USER).sees_staff_names
    assert all(_scope(r).sees_staff_names for r in (Role.ADMIN, Role.BIOMEDICAL_ENGINEER, Role.TECHNICIAN))


# ---- response builder ------------------------------------------------------------------------------
def _user(uid, name, role):
    return SimpleNamespace(id=uid, full_name=name, role=SimpleNamespace(name=role))


def _ticket(reporter_id):
    dev = SimpleNamespace(id=uuid.uuid4(), device_code="DEV-001", name="Ventilator", department_id=uuid.uuid4(),
                          department=SimpleNamespace(name="ICU"), serial_number="SECRET", criticality="critical")
    active = SimpleNamespace(user=_user(TECH, "Tarek Tech", "technician"), assigned_at=T0)
    return SimpleNamespace(
        id=uuid.UUID("3f9a1c2b-7d4e-4a1b-9c3d-2e5f6a7b8c9d"), status=TicketStatus.ASSIGNED, priority=TicketPriority.HIGH,
        problem_description="[Power issue] Won't start", device=dev, hospital_id=uuid.uuid4(),
        reporter=_user(reporter_id, "Nora Nurse", "department_user"), active_assignments=[active],
        is_deleted=False, created_at=T0, updated_at=T0, resolved_at=None,
    )


def test_response_for_a_department_user_hides_staff_identity_and_device_internals():
    viewer = _scope(Role.DEPARTMENT_USER)
    body = TicketResponse.build(_ticket(viewer.user_id), viewer).model_dump(mode="json")
    assert body["number"] == "TKT-3F9A1C2B"
    assert (body["category"], body["description"]) == ("Power issue", "Won't start")
    assert set(body["device"]) == {"id", "device_code", "name", "department_id", "department_name"}
    assert body["reported_by"]["name"] == "Nora Nurse" and body["reported_by"]["id"] == str(viewer.user_id)
    assert body["assignees"] == [{"id": None, "name": "Technician", "role": "technician", "assigned_at": "2026-11-01T09:00:00Z"}]


def test_response_for_staff_shows_names_and_ids():
    viewer = _scope(Role.BIOMEDICAL_ENGINEER)
    body = TicketResponse.build(_ticket(REPORTER), viewer).model_dump(mode="json")
    assert body["reported_by"] == {"id": str(REPORTER), "name": "Nora Nurse", "role": "department_user"}
    assert body["assignees"][0]["id"] == str(TECH) and body["assignees"][0]["name"] == "Tarek Tech"
