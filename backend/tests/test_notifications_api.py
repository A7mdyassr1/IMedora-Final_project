"""B5 CP3 - in-app notifications against REAL PostgreSQL: who is notified of each ticket and device
event, no staff names for department users, the caller-only inbox, read / read-all (idempotent,
database clock, audited), and notifications living and dying with their event's transaction.
Skipped unless TEST_DATABASE_URL is set; everything created here is removed (tests/ticket_scene.py,
tests/world.py: notifications cascade with their users).
"""
import uuid

import pytest

from app.services.notification_service import Notifier
from tests.scope_scene import scene  # noqa: F401
from tests.test_devices_flow import cat  # noqa: F401
from tests.ticket_scene import tickets  # noqa: F401
from tests.world import API


def _inbox(client, headers, **params):
    r = client.get(f"{API}/notifications", headers=headers, params={"page_size": 100, **params})
    assert r.status_code == 200, r.text
    return r.json()


def _of(client, headers, ticket_id=None, kind=None):
    items = _inbox(client, headers)["items"]
    return [n for n in items if (ticket_id is None or n["related_ticket_id"] == ticket_id)
            and (kind is None or n["type"] == kind)]


def _me(client, headers):
    return client.get(f"{API}/auth/me", headers=headers).json()


def test_reporting_notifies_the_reporter_and_the_hospitals_biomedical_team(client, tickets):
    h = tickets["h"]
    r = tickets["report"](h["dept_icu"], "icu")
    t = r.json()
    mine = _of(client, h["dept_icu"], t["id"])
    assert [(n["type"], n["title"], n["is_read"], n["ticket_number"]) for n in mine] == [
        ("ticket_created", "Maintenance request received", False, t["number"])]
    assert mine[0]["body"] == f"{t['number']} (ICU ventilator (S-ICU)) was received. The biomedical team has been notified."
    for staff in ("eng_h1", "tech_h1"):
        got = _of(client, h[staff], t["id"])
        assert [(n["type"], n["title"]) for n in got] == [("ticket_created", "New maintenance request")], staff
        assert "ICU" in got[0]["body"] and "medium priority" in got[0]["body"]
    for nobody in ("admin", "eng_h2", "tech_h2", "dept_none"):
        assert _of(client, h[nobody], t["id"]) == [], nobody
    # the inactive technician of H1 (world fixture) is not notified
    inactive = tickets["sql"]("SELECT count(*) FROM notifications n JOIN users u ON u.id = n.user_id "
                              "WHERE u.email = :e", e=tickets["world"]["inactive"])[0][0]
    assert inactive == 0
    # ticket, notifications and their audit rows: one transaction
    (xmin, ), = tickets["sql"]("SELECT xmin::text FROM maintenance_tickets WHERE id = :t", t=t["id"])
    notes = tickets["sql"]("SELECT DISTINCT xmin::text FROM notifications WHERE related_ticket_id = :t", t=t["id"])
    audit = tickets["sql"]("SELECT DISTINCT xmin::text FROM audit_logs WHERE table_name = 'notifications' AND "
                           "new_values->>'related_ticket_id' = :t", t=t["id"])
    assert notes == [(xmin,)] and audit == [(xmin,)]


def test_assignment_and_status_changes_notify_reporter_and_assignees_never_the_actor(client, tickets):
    h = tickets["h"]
    tid = tickets["report"](h["dept_icu"], "icu").json()["id"]
    tech = _me(client, h["tech_h1"])
    assert client.post(f"{API}/tickets/{tid}/assignments", headers=h["eng_h1"], json={"user_id": tech["id"]}).status_code == 201
    assigned = _of(client, h["tech_h1"], tid, "ticket_assigned")
    assert [n["title"] for n in assigned] == ["Ticket assigned to you"]
    reporter = _of(client, h["dept_icu"], tid, "ticket_assigned")
    assert [n["body"].split(" was assigned")[0] for n in reporter] == ["A technician"]
    assert _of(client, h["eng_h1"], tid, "ticket_assigned") == []          # the actor

    assert client.patch(f"{API}/tickets/{tid}/status", headers=h["tech_h1"], json={"status": "in_progress"}).status_code == 200
    assert [n["title"] for n in _of(client, h["dept_icu"], tid, "ticket_status_changed")] == ["Ticket in progress"]
    assert _of(client, h["tech_h1"], tid, "ticket_status_changed") == []    # the actor
    assert client.patch(f"{API}/tickets/{tid}/status", headers=h["eng_h1"],
                        json={"status": "waiting_for_parts"}).status_code == 200
    assert "Waiting for parts" in [n["title"] for n in _of(client, h["tech_h1"], tid, "ticket_status_changed")]

    mtype = tickets["mtype"]("corrective")
    assert client.post(f"{API}/maintenance-records", headers=h["tech_h1"], json={
        "device_id": tickets["d"]["icu"]["id"], "maintenance_type_id": mtype, "ticket_id": tid,
        "description": "Recalibrated the pressure sensor"}).status_code == 201
    assert client.patch(f"{API}/tickets/{tid}/status", headers=h["tech_h1"], json={"status": "resolved"}).status_code == 200
    resolved = _of(client, h["dept_icu"], tid, "ticket_resolved")
    assert [n["title"] for n in resolved] == ["Ticket resolved"]
    assert resolved[0]["body"].endswith("was resolved: Recalibrated the pressure sensor")
    assert client.patch(f"{API}/tickets/{tid}/status", headers=h["eng_h1"], json={"status": "closed"}).status_code == 200
    for who in ("dept_icu", "tech_h1"):
        assert "Ticket closed" in [n["title"] for n in _of(client, h[who], tid, "ticket_status_changed")], who

    # department users never see staff names (Q9)
    names = {tech["full_name"], _me(client, h["eng_h1"])["full_name"]}
    for n in _of(client, h["dept_icu"], tid):
        assert not any(name in (n["title"] + (n["body"] or "")) for name in names), n


def test_self_assignment_reopen_unassign_and_cancel(client, tickets):
    h = tickets["h"]
    tid = tickets["report"](h["dept_icu"], "icu").json()["id"]
    tech = _me(client, h["tech_h1"])
    assert client.post(f"{API}/tickets/{tid}/assignments", headers=h["tech_h1"], json={"user_id": tech["id"]}).status_code == 201
    assert _of(client, h["tech_h1"], tid, "ticket_assigned") == []           # took it themselves
    assert len(_of(client, h["dept_icu"], tid, "ticket_assigned")) == 1
    assert client.delete(f"{API}/tickets/{tid}/assignments/{tech['id']}", headers=h["eng_h1"]).status_code == 200
    back = _of(client, h["dept_icu"], tid, "ticket_status_changed")
    assert [n["title"] for n in back] == ["Waiting for a technician"]

    # the reporter cancels their own open ticket: nobody else is concerned, nobody is notified
    before = tickets["sql"]("SELECT count(*) FROM notifications WHERE related_ticket_id = :t", t=tid)[0][0]
    assert client.patch(f"{API}/tickets/{tid}/status", headers=h["dept_icu"], json={"status": "cancelled"}).status_code == 200
    assert tickets["sql"]("SELECT count(*) FROM notifications WHERE related_ticket_id = :t", t=tid)[0][0] == before


def test_a_refused_change_notifies_nobody(client, tickets):
    h = tickets["h"]
    tid = tickets["report"](h["dept_icu"], "icu").json()["id"]
    tech = _me(client, h["tech_h1"])
    client.post(f"{API}/tickets/{tid}/assignments", headers=h["eng_h1"], json={"user_id": tech["id"]})
    client.patch(f"{API}/tickets/{tid}/status", headers=h["tech_h1"], json={"status": "in_progress"})
    before = tickets["sql"]("SELECT count(*) FROM notifications WHERE related_ticket_id = :t", t=tid)[0][0]
    r = client.patch(f"{API}/tickets/{tid}/status", headers=h["tech_h1"], json={"status": "resolved"})  # no record (Q7)
    assert r.status_code == 409
    assert tickets["sql"]("SELECT count(*) FROM notifications WHERE related_ticket_id = :t", t=tid)[0][0] == before


def test_notifications_roll_back_with_their_event(client, tickets, monkeypatch):
    """A failure AFTER the notifications were written (here: in the producer itself) rolls back the
    ticket AND the notifications: neither exists."""
    h = tickets["h"]
    original = Notifier._send

    def send_then_fail(self, *args, **kwargs):
        original(self, *args, **kwargs)
        raise RuntimeError("simulated failure after the notifications were added")

    monkeypatch.setattr(Notifier, "_send", send_then_fail)
    marker = f"rollback-{uuid.uuid4().hex[:8]}"
    with pytest.raises(RuntimeError):
        tickets["report"](h["dept_icu"], "icu", description=marker)
    monkeypatch.undo()
    assert tickets["sql"]("SELECT count(*) FROM maintenance_tickets WHERE problem_description LIKE :m", m=f"%{marker}%")[0][0] == 0
    assert tickets["sql"]("SELECT count(*) FROM notifications WHERE body LIKE :m", m="%S-ICU%was received%")[0][0] == 0


def test_device_status_alerts_its_department_users(client, tickets):
    h, d = tickets["h"], tickets["d"]
    lab_user = tickets["add_user"]("lab-user", "department_user", "h1", tickets["lab"])
    url = f"{API}/devices/{d['icu']['id']}"
    assert client.patch(url, headers=h["eng_h1"], json={"status": "under_maintenance"}).status_code == 200
    alerts = _of(client, h["dept_icu"], kind="device_alert")
    assert [(n["title"], n["body"], n["related_ticket_id"]) for n in alerts] == [
        ("Important device notice", "ICU ventilator (S-ICU) is under maintenance. Please use an alternative device.", None)]
    assert _of(client, lab_user, kind="device_alert") == []
    assert _of(client, h["eng_h1"], kind="device_alert") == []
    assert client.patch(url, headers=h["eng_h1"], json={"name": "ICU ventilator 2"}).status_code == 200   # no status change
    assert len(_of(client, h["dept_icu"], kind="device_alert")) == 1
    assert client.patch(url, headers=h["eng_h1"], json={"status": "active"}).status_code == 200
    assert [n["title"] for n in _of(client, h["dept_icu"], kind="device_alert")][0] == "Device back in service"


def test_inbox_is_private_and_read_state_is_idempotent(client, tickets):
    h = tickets["h"]
    t1 = tickets["report"](h["dept_icu"], "icu").json()["id"]
    t2 = tickets["report"](h["dept_icu"], "lab").json()["id"]
    box = _inbox(client, h["dept_icu"])
    assert [n["related_ticket_id"] for n in box["items"][:2]] == [t2, t1]   # newest first
    assert box["unread_count"] == 2 == box["total"]
    first = box["items"][0]

    _err = lambda r, s: r.status_code == s
    assert _err(client.patch(f"{API}/notifications/{first['id']}/read", headers=h["tech_h1"]), 404)   # not theirs
    assert _err(client.patch(f"{API}/notifications/{first['id']}/read", headers=h["admin"]), 404)     # not even admins
    assert _err(client.patch(f"{API}/notifications/{uuid.uuid4()}/read", headers=h["dept_icu"]), 404)

    r = client.patch(f"{API}/notifications/{first['id']}/read", headers=h["dept_icu"])
    assert r.status_code == 200 and r.json()["is_read"] is True and r.json()["read_at"] >= r.json()["created_at"]
    again = client.patch(f"{API}/notifications/{first['id']}/read", headers=h["dept_icu"]).json()
    assert again["read_at"] == r.json()["read_at"]
    assert _inbox(client, h["dept_icu"])["unread_count"] == 1
    assert [n["id"] for n in _inbox(client, h["dept_icu"], unread_only=True)["items"]] == [box["items"][1]["id"]]

    tech_unread = _inbox(client, h["tech_h1"])["unread_count"]
    assert client.post(f"{API}/notifications/read-all", headers=h["dept_icu"]).json() == {"updated": 1}
    assert client.post(f"{API}/notifications/read-all", headers=h["dept_icu"]).json() == {"updated": 0}
    assert _inbox(client, h["dept_icu"])["unread_count"] == 0
    assert _inbox(client, h["tech_h1"])["unread_count"] == tech_unread        # nobody else's changed
    audited = tickets["sql"]("SELECT count(*) FROM audit_logs WHERE table_name = 'notifications' AND action = 'update' "
                             "AND user_id = (SELECT id FROM users WHERE email = :e)", e=tickets["world"]["staff"])[0][0]
    assert audited == 2

    # a department user who lost their department still reads their notifications (as their reports, Q11)
    assert _inbox(client, h["dept_none"])["total"] == 0
    assert client.get(f"{API}/notifications", headers=h["dept_none"]).status_code == 200
    assert client.get(f"{API}/notifications").status_code == 401
