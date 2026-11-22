"""B4 CP2 - database-free tests of the ticket workflow: the full 7x7 transition table, who may
set each status / assign / unassign / change priority (Q4-Q6), and timeline v2 (assignment
events, folding of the automatic status change, privacy)."""
import itertools
import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.access import AccessScope, DeviceAccess
from app.core.enums import TicketStatus as S
from app.core.roles import Role
from app.core.ticket_workflow import (
    MANUAL_TRANSITIONS, InvalidStatusTransitionError, TicketFacts, check_transition, may_assign,
    may_change_priority, may_set_status, may_unassign,
)
from app.services.ticket_timeline import AssignmentEntry, AuditEntry, Person, build_timeline

H1, H2 = uuid.uuid4(), uuid.uuid4()

EXPECTED = {  # the approved table, written out independently of the implementation
    ("open", "cancelled"), ("assigned", "in_progress"), ("assigned", "cancelled"),
    ("in_progress", "waiting_for_parts"), ("in_progress", "resolved"), ("in_progress", "cancelled"),
    ("waiting_for_parts", "in_progress"), ("waiting_for_parts", "resolved"), ("waiting_for_parts", "cancelled"),
    ("resolved", "closed"), ("resolved", "in_progress"),
}


@pytest.mark.parametrize("current, target", list(itertools.product(list(S), list(S))))
def test_full_transition_table(current, target):
    if (current.value, target.value) in EXPECTED:
        check_transition(current, target)
    else:
        with pytest.raises(InvalidStatusTransitionError) as exc:
            check_transition(current, target)
        assert exc.value.code == "invalid_status_transition" and exc.value.status_code == 409
        assert exc.value.details == [{"from": current.value, "to": target.value,
                                      "allowed": sorted(s.value for s in MANUAL_TRANSITIONS[current])}]


def test_open_and_assigned_are_never_set_by_hand_and_terminal_states_are_final():
    assert all(S.OPEN not in t and S.ASSIGNED not in t for t in MANUAL_TRANSITIONS.values())
    assert MANUAL_TRANSITIONS[S.CLOSED] == frozenset() == MANUAL_TRANSITIONS[S.CANCELLED]


# ---- who may do what -------------------------------------------------------------------------------
def _scope(role, hospital=H1, user=None):
    access = DeviceAccess.ORGANIZATION if role is Role.ADMIN else DeviceAccess.HOSPITAL
    if role is Role.DEPARTMENT_USER:
        access = DeviceAccess.DEPARTMENT
    return AccessScope(user or uuid.uuid4(), role, uuid.uuid4(), hospital, uuid.uuid4(), access)


def _ticket(status, reporter=None, assignees=(), hospital=H1):
    return TicketFacts(hospital, reporter or uuid.uuid4(), status, frozenset(assignees))


admin, eng, eng_h2 = _scope(Role.ADMIN), _scope(Role.BIOMEDICAL_ENGINEER), _scope(Role.BIOMEDICAL_ENGINEER, H2)
tech, tech_h2, dept = _scope(Role.TECHNICIAN), _scope(Role.TECHNICIAN, H2), _scope(Role.DEPARTMENT_USER)


@pytest.mark.parametrize("target", [S.IN_PROGRESS, S.WAITING_FOR_PARTS, S.RESOLVED])
def test_work_statuses_need_an_active_assignee_or_a_manager(target):
    t = _ticket(S.ASSIGNED, assignees=[tech.user_id])
    assert may_set_status(tech, t, target)                                   # Q5: assigned technician
    assert not may_set_status(_scope(Role.TECHNICIAN), t, target)            # other technician
    assert may_set_status(eng, t, target) and may_set_status(admin, t, target)
    assert not may_set_status(eng_h2, t, target)                             # engineer of another hospital
    assert not may_set_status(dept, _ticket(S.ASSIGNED, reporter=dept.user_id), target)
    assigned_eng = _scope(Role.BIOMEDICAL_ENGINEER, H2)
    assert not may_set_status(assigned_eng, _ticket(S.ASSIGNED, assignees=[assigned_eng.user_id]), target)  # wrong hospital


def test_close_and_reopen_are_for_engineers_and_admins_only():
    t = _ticket(S.RESOLVED, assignees=[tech.user_id])
    for target in (S.CLOSED, S.IN_PROGRESS):
        assert may_set_status(eng, t, target) and may_set_status(admin, t, target)  # Q6
        assert not may_set_status(tech, t, target)                                  # even when assigned
        assert not may_set_status(eng_h2, t, target)
        assert not may_set_status(dept, _ticket(S.RESOLVED, reporter=dept.user_id), target)


def test_cancel_rules_including_the_reporter_exception():
    assert may_set_status(eng, _ticket(S.IN_PROGRESS), S.CANCELLED) and may_set_status(admin, _ticket(S.OPEN), S.CANCELLED)
    assert not may_set_status(tech, _ticket(S.ASSIGNED, assignees=[tech.user_id]), S.CANCELLED)
    # Q4: the reporter, only while open with no active assignment
    assert may_set_status(dept, _ticket(S.OPEN, reporter=dept.user_id), S.CANCELLED)
    assert may_set_status(tech, _ticket(S.OPEN, reporter=tech.user_id), S.CANCELLED)
    assert not may_set_status(dept, _ticket(S.ASSIGNED, reporter=dept.user_id, assignees=[tech.user_id]), S.CANCELLED)
    assert not may_set_status(dept, _ticket(S.OPEN, reporter=dept.user_id, assignees=[tech.user_id]), S.CANCELLED)
    assert not may_set_status(dept, _ticket(S.OPEN), S.CANCELLED)  # someone else's ticket


def test_assignment_rules():
    t = _ticket(S.OPEN)
    other = uuid.uuid4()
    assert may_assign(eng, t, other) and may_assign(admin, t, other)
    assert may_assign(tech, t, tech.user_id) and not may_assign(tech, t, other)   # Q5: self only
    assert not may_assign(tech_h2, t, tech_h2.user_id)                            # other hospital
    assert not may_assign(eng_h2, t, other) and not may_assign(dept, t, dept.user_id)
    assert may_unassign(tech, t, tech.user_id) and not may_unassign(tech, t, other)
    assert may_unassign(eng, t, other) and not may_unassign(dept, t, other)


def test_priority_is_for_engineers_and_admins():
    t = _ticket(S.OPEN, reporter=dept.user_id)
    assert may_change_priority(eng, t) and may_change_priority(admin, t)
    assert not any(may_change_priority(s, t) for s in (tech, dept, eng_h2))


# ---- timeline v2 ----------------------------------------------------------------------------------
T0 = datetime(2026, 11, 1, 9, 0, tzinfo=timezone.utc)
REP, TECH, ENG = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
PEOPLE = {REP: Person(REP, "Nora Nurse", "department_user"), TECH: Person(TECH, "Tarek Tech", "technician"),
          ENG: Person(ENG, "Eman Eng", "biomedical_engineer")}


def _at(m):
    return T0 + timedelta(minutes=m)


def _flow(viewer=ENG, names=True, **extra):
    audit = [
        AuditEntry(T0, "insert", REP, None, {"status": "open"}),
        AuditEntry(_at(5), "update", ENG, {"status": "open"}, {"status": "assigned"}),       # automatic, folded
        AuditEntry(_at(10), "update", TECH, {"status": "assigned"}, {"status": "in_progress"}),
        AuditEntry(_at(30), "update", ENG, {"status": "in_progress"}, {"status": "resolved"}),
    ]
    assignments = [AssignmentEntry(TECH, _at(5), assigned_by=ENG)]
    return build_timeline(ticket_created_at=T0, reporter_id=REP, audit=audit, people=PEOPLE, viewer_id=viewer,
                          viewer_sees_names=names, assignments=assignments, **extra)


def test_assignment_event_absorbs_the_automatic_status_change():
    items = _flow()
    assert [(i.kind, i.status, i.message, i.actor) for i in items] == [
        ("created", S.OPEN, "Ticket created.", "Nora Nurse"),
        ("assigned", S.ASSIGNED, "Assigned to Tarek Tech.", "Eman Eng"),
        ("status_changed", S.IN_PROGRESS, "Status changed to In Progress.", "Tarek Tech"),
        ("status_changed", S.RESOLVED, "Status changed to Resolved.", "Eman Eng"),
    ]


def test_department_user_sees_roles_in_assignment_events():
    items = _flow(viewer=REP, names=False)
    assert items[1].message == "Assigned to Technician." and items[1].actor == "Biomedical engineer"
    assert "Tarek" not in repr(items) and "Eman" not in repr(items)


def test_unassignment_back_to_open_is_one_event_and_a_second_assignee_keeps_status():
    audit = [AuditEntry(T0, "insert", REP, None, {"status": "open"}),
             AuditEntry(_at(1), "update", ENG, {"status": "open"}, {"status": "assigned"}),
             AuditEntry(_at(3), "update", ENG, {"status": "assigned"}, {"status": "open"})]
    assignments = [AssignmentEntry(TECH, _at(1), _at(3), assigned_by=ENG, unassigned_by=ENG),
                   AssignmentEntry(ENG, _at(2), assigned_by=ENG)]
    items = build_timeline(ticket_created_at=T0, reporter_id=REP, audit=audit, people=PEOPLE, viewer_id=ENG,
                           viewer_sees_names=True, assignments=assignments)
    assert [(i.kind, i.status, i.message) for i in items] == [
        ("created", S.OPEN, "Ticket created."),
        ("assigned", S.ASSIGNED, "Assigned to Tarek Tech."),
        ("assigned", S.ASSIGNED, "Assigned to Eman Eng."),
        ("unassigned", S.OPEN, "Tarek Tech unassigned."),
    ]


def test_status_change_at_another_time_is_not_folded_and_seeded_assignments_have_no_actor():
    audit = [AuditEntry(T0, "insert", REP, None, {"status": "open"}),
             AuditEntry(_at(9), "update", ENG, {"status": "open"}, {"status": "assigned"})]
    items = build_timeline(ticket_created_at=T0, reporter_id=REP, audit=audit, people=PEOPLE, viewer_id=ENG,
                           viewer_sees_names=True, assignments=[AssignmentEntry(TECH, _at(5))])
    assert [(i.kind, i.status, i.actor) for i in items] == [
        ("created", S.OPEN, "Nora Nurse"), ("assigned", S.OPEN, None), ("status_changed", S.ASSIGNED, "Eman Eng")]


def test_unknown_assignee_is_described_neutrally():
    stranger = uuid.uuid4()
    items = build_timeline(ticket_created_at=T0, reporter_id=REP, audit=[], people=PEOPLE, viewer_id=ENG,
                           viewer_sees_names=True, assignments=[AssignmentEntry(stranger, _at(1))])
    assert items[1].message == "Assigned to a staff member."
