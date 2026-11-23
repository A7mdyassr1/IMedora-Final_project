"""B5 CP3 unit tests (no database): notification texts and when device alerts fire."""
import uuid
from types import SimpleNamespace

import pytest

from app.core.enums import DeviceStatus, TicketPriority, TicketStatus
from app.services import notification_service as ns
from app.services.notification_service import Notifier, _shorten


class _Recorder(Notifier):
    """A Notifier whose database parts are replaced: records what it would send."""

    def __init__(self, team=(), department_users=()):
        self.sent = []
        self.repo = SimpleNamespace(hospital_staff=lambda *a: list(team), department_users=lambda *a: list(department_users))

    def _send(self, actor_id, organization_id, recipients, kind, title, body, ticket_id=None, notify_actor=False):
        wanted = {r for r in recipients if r is not None and (notify_actor or r != actor_id)}
        self.sent.append((kind, title, body, sorted(map(str, wanted))))


def _ticket(**kw):
    device = SimpleNamespace(name="Ventilator", device_code="DEV-001", department=SimpleNamespace(name="ICU"))
    base = dict(id=uuid.UUID("3f9a1c2b-0000-4000-8000-000000000000"), organization_id=uuid.uuid4(),
                hospital_id=uuid.uuid4(), reported_by=uuid.uuid4(), device=device, device_id=uuid.uuid4(),
                priority=TicketPriority.HIGH, active_assignments=[])
    base.update(kw)
    return SimpleNamespace(**base)


def test_ticket_created_texts_and_recipients():
    t = _ticket()
    engineer = uuid.uuid4()
    n = _Recorder(team=[engineer, t.reported_by])
    n.ticket_created(t.reported_by, t)
    (k1, title1, body1, to1), (k2, title2, body2, to2) = n.sent
    assert (k1, title1, to1) == ("ticket_created", "Maintenance request received", [str(t.reported_by)])
    assert body1 == "TKT-3F9A1C2B (Ventilator (DEV-001)) was received. The biomedical team has been notified."
    assert (k2, title2, to2) == ("ticket_created", "New maintenance request", [str(engineer)])
    assert body2 == "TKT-3F9A1C2B (Ventilator (DEV-001)), ICU: high priority."


def test_assignment_text_names_a_role_never_a_person():
    t = _ticket()
    tech = uuid.uuid4()
    n = _Recorder()
    n.ticket_assigned(uuid.uuid4(), t, tech, "biomedical_engineer")
    assert [s[1] for s in n.sent] == ["Ticket assigned to you", "Technician assigned"]
    assert n.sent[1][2] == "A biomedical engineer was assigned to TKT-3F9A1C2B (Ventilator (DEV-001))."


@pytest.mark.parametrize("old, new, title", [
    (TicketStatus.ASSIGNED, TicketStatus.IN_PROGRESS, "Ticket in progress"),
    (TicketStatus.IN_PROGRESS, TicketStatus.WAITING_FOR_PARTS, "Waiting for parts"),
    (TicketStatus.RESOLVED, TicketStatus.CLOSED, "Ticket closed"),
    (TicketStatus.OPEN, TicketStatus.CANCELLED, "Ticket cancelled"),
    (TicketStatus.RESOLVED, TicketStatus.IN_PROGRESS, "Ticket reopened"),
    (TicketStatus.ASSIGNED, TicketStatus.OPEN, "Waiting for a technician"),
])
def test_status_change_titles_go_to_reporter_and_assignees_not_the_actor(old, new, title):
    actor, other = uuid.uuid4(), uuid.uuid4()
    t = _ticket(active_assignments=[SimpleNamespace(user_id=actor), SimpleNamespace(user_id=other)])
    n = _Recorder()
    n.ticket_status_changed(actor, t, old, new)
    assert [(s[0], s[1]) for s in n.sent] == [("ticket_status_changed", title)]
    assert n.sent[0][3] == sorted([str(t.reported_by), str(other)])


def test_assigned_status_is_announced_by_the_assignment_only():
    n = _Recorder()
    n.ticket_status_changed(uuid.uuid4(), _ticket(), TicketStatus.OPEN, TicketStatus.ASSIGNED)
    assert n.sent == []


@pytest.mark.parametrize("old, new, title", [
    (DeviceStatus.ACTIVE, DeviceStatus.UNDER_MAINTENANCE, "Important device notice"),
    (DeviceStatus.ACTIVE, DeviceStatus.OUT_OF_SERVICE, "Important device notice"),
    (DeviceStatus.OUT_OF_SERVICE, DeviceStatus.ACTIVE, "Device back in service"),
    (DeviceStatus.ACTIVE, DeviceStatus.ACTIVE, None),
    (DeviceStatus.ACTIVE, DeviceStatus.DECOMMISSIONED, None),
])
def test_device_alerts(old, new, title):
    user = uuid.uuid4()
    n = _Recorder(department_users=[user])
    device = SimpleNamespace(name="Pump", device_code="P-1", organization_id=uuid.uuid4(), department_id=uuid.uuid4())
    n.device_status_changed(uuid.uuid4(), device, old, new)
    assert [s[1] for s in n.sent] == ([title] if title else [])


def test_work_summary_is_shortened_on_one_line():
    assert _shorten("a\n  b   c") == "a b c"
    long = _shorten("x" * 400)
    assert len(long) == ns.WORK_SUMMARY_MAX and long.endswith("…")
