"""B4 CP3 - maintenance management against REAL PostgreSQL: types, records, schedules,
devices.next_maintenance_due_date, the complete API-only ticket resolution, permissions and
hospital scoping, audit in the same transaction, and row locking under concurrent requests.
Skipped unless TEST_DATABASE_URL is set; everything created here is removed (tests/ticket_scene.py).
"""
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.database import get_session_factory
from tests.scope_scene import scene  # noqa: F401
from tests.test_devices_flow import cat  # noqa: F401
from tests.ticket_scene import tickets  # noqa: F401
from tests.world import API


def _me(client, headers):
    return client.get(f"{API}/auth/me", headers=headers).json()["id"]


def _err(r, status, code=None, message=None):
    assert r.status_code == status, r.text
    if code:
        assert r.json()["error"]["code"] == code, r.text
    if message:
        assert r.json()["error"]["message"] == message, r.text


def _status(client, headers, tid, status):
    return client.patch(f"{API}/tickets/{tid}/status", headers=headers, json={"status": status})


def _record(client, headers, device_id, type_id, description="Replaced the power supply", **extra):
    return client.post(f"{API}/maintenance-records", headers=headers,
                       json={"device_id": device_id, "maintenance_type_id": type_id, "description": description, **extra})


def _schedule(client, headers, device_id, type_id, due, frequency=90):
    return client.post(f"{API}/maintenance-schedules", headers=headers,
                       json={"device_id": device_id, "maintenance_type_id": type_id, "frequency_days": frequency,
                             "next_due_date": str(due)})


def _next_due(client, tickets, key):
    return client.get(f"{API}/devices/{tickets['d'][key]['id']}", headers=tickets["h"]["admin"]).json()["next_maintenance_due_date"]


def _today(tickets):
    return tickets["sql"]("SELECT current_date")[0][0]


def _in_progress_ticket(client, tickets, device="icu"):
    h, w = tickets["h"], tickets["world"]
    tid = tickets["report"](h["dept_icu"] if device == "icu" else h["tech_h1"], device).json()["id"]
    assert client.post(f"{API}/tickets/{tid}/assignments", headers=h["eng_h1"], json={"user_id": w["tech_id"]}).status_code == 201
    assert _status(client, h["tech_h1"], tid, "in_progress").status_code == 200
    return tid


# ---- the complete flow, API only ------------------------------------------------------------------
def test_ticket_is_resolved_entirely_through_the_api(client, tickets):
    """report -> assign -> in progress -> (resolve refused) -> record work -> resolve -> close."""
    h, d = tickets["h"], tickets["d"]
    corrective = tickets["mtype"]("corrective")
    device_status = client.get(f"{API}/devices/{d['icu']['id']}", headers=h["admin"]).json()["status"]
    tid = _in_progress_ticket(client, tickets)
    _err(_status(client, h["tech_h1"], tid, "resolved"), 409, "maintenance_record_required")

    r = _record(client, h["tech_h1"], d["icu"]["id"], corrective, description="Replaced the power supply", ticket_id=tid)
    assert r.status_code == 201, r.text
    rec = r.json()
    number = client.get(f"{API}/tickets/{tid}", headers=h["tech_h1"]).json()["number"]
    assert rec["ticket_id"] == tid and rec["ticket_number"] == number and rec["schedule_id"] is None
    assert rec["performed_by"]["id"] == tickets["world"]["tech_id"] and rec["maintenance_type"]["id"] == corrective
    assert rec["device"]["device_code"] == "S-ICU" and rec["device"]["is_archived"] is False

    assert _status(client, h["tech_h1"], tid, "resolved").status_code == 200
    closed = _status(client, h["eng_h1"], tid, "closed").json()
    assert closed["status"] == "closed"
    kinds = [(i["kind"], i["status"]) for i in closed["timeline"]]
    assert kinds == [("created", "open"), ("assigned", "assigned"), ("status_changed", "in_progress"),
                     ("work_performed", "in_progress"), ("status_changed", "resolved"), ("status_changed", "closed")]
    work = closed["timeline"][3]
    assert work["message"] == "Work performed: Replaced the power supply" and work["actor"] == tickets["world"]["tech"].split("@")[0]
    # the reporter sees the work description, with the technician as a role (Q9)
    own = client.get(f"{API}/tickets/{tid}", headers=h["dept_icu"]).json()["timeline"][3]
    assert own["message"] == "Work performed: Replaced the power supply" and own["actor"] == "Technician"
    # Q8: the device status is untouched; no schedule, so no next maintenance date either
    device = client.get(f"{API}/devices/{d['icu']['id']}", headers=h["admin"]).json()
    assert device["status"] == device_status and device["next_maintenance_due_date"] is None


def test_record_and_its_audit_row_are_written_in_one_transaction(client, tickets):
    h, d, sql = tickets["h"], tickets["d"], tickets["sql"]
    preventive = tickets["mtype"]("preventive")
    sid = _schedule(client, h["eng_h1"], d["icu"]["id"], preventive, _today(tickets) + timedelta(days=10), 30).json()["id"]
    rid = _record(client, h["tech_h1"], d["icu"]["id"], preventive, schedule_id=sid).json()["id"]
    rec_xmin = sql("SELECT xmin::text FROM maintenance_records WHERE id = :i", i=rid)[0][0]
    rows = sql("SELECT table_name, action::text, xmin::text FROM audit_logs WHERE created_at = "
               "(SELECT created_at FROM audit_logs WHERE record_id = :i) ORDER BY table_name", i=rid)
    assert [(r[0], r[1]) for r in rows] == [("devices", "update"), ("maintenance_records", "insert"),
                                           ("maintenance_schedules", "update")]
    assert {r[2] for r in rows} == {rec_xmin}
    assert sql("SELECT xmin::text FROM maintenance_schedules WHERE id = :i", i=sid)[0][0] == rec_xmin


# ---- records: permissions and validation --------------------------------------------------------------
def test_record_creation_rules(client, tickets):
    h, d, w = tickets["h"], tickets["d"], tickets["world"]
    t = tickets["mtype"]("corrective")
    for who in ("dept_icu", "dept_none"):
        _err(_record(client, h[who], d["icu"]["id"], t), 403)
    _err(_record(client, h["tech_h1"], d["h2"]["id"], t), 404, message="Device not found.")
    _err(_record(client, h["eng_h2"], d["icu"]["id"], t), 404)
    assert _record(client, h["tech_h1"], d["icu"]["id"], t).status_code == 201       # unlinked work
    assert _record(client, h["admin"], d["h2"]["id"], t).status_code == 201
    _err(_record(client, h["tech_h1"], d["archived"]["id"], t), 400, message="Archived devices cannot receive new maintenance data.")
    _err(_record(client, h["tech_h1"], d["icu"]["id"], str(uuid.uuid4())), 400, message="Unknown maintenance type.")
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    _err(_record(client, h["tech_h1"], d["icu"]["id"], t, performed_at=future), 400, message="The work date cannot be in the future.")
    for extra in ({"performed_by": w["admin_id"]}, {"hospital_id": w["h1"]}, {"description": " "}):
        body = {"device_id": d["icu"]["id"], "maintenance_type_id": t, "description": "x", **extra}
        assert client.post(f"{API}/maintenance-records", headers=h["tech_h1"], json=body).status_code == 422, extra

    # linked to a ticket
    h["tech_b"] = tickets["add_user"]("tech-h1-m", "technician", "h1")
    tid = _in_progress_ticket(client, tickets)
    _err(_record(client, h["tech_b"], d["icu"]["id"], t, ticket_id=tid), 403)                  # not assigned (Q5)
    assert _record(client, h["eng_h1"], d["icu"]["id"], t, ticket_id=tid).status_code == 201   # engineer of the hospital
    _err(_record(client, h["tech_h1"], d["lab"]["id"], t, ticket_id=tid), 400,
         message="The ticket does not exist or belongs to another device.")
    _err(_record(client, h["tech_h1"], d["icu"]["id"], t, ticket_id=str(uuid.uuid4())), 400)
    h2_ticket = tickets["report"](h["eng_h2"], "h2").json()["id"]
    _err(_record(client, h["tech_h1"], d["icu"]["id"], t, ticket_id=h2_ticket), 400)           # invisible ticket
    before = (datetime.fromisoformat(client.get(f"{API}/tickets/{tid}", headers=h["admin"]).json()["created_at"])
              - timedelta(hours=1)).isoformat()
    _err(_record(client, h["tech_h1"], d["icu"]["id"], t, ticket_id=tid, performed_at=before), 400,
         message="Work on a ticket cannot be dated before the ticket was reported.")
    cancelled = tickets["report"](h["tech_h1"], "icu").json()["id"]
    assert _status(client, h["eng_h1"], cancelled, "cancelled").status_code == 200
    _err(_record(client, h["eng_h1"], d["icu"]["id"], t, ticket_id=cancelled), 409,
         message="Closed or cancelled tickets cannot receive maintenance records.")
    deleted = tickets["report"](h["tech_h1"], "icu").json()["id"]
    assert client.delete(f"{API}/tickets/{deleted}", headers=h["admin"]).status_code == 204
    _err(_record(client, h["admin"], d["icu"]["id"], t, ticket_id=deleted), 409, message="Deleted tickets cannot be modified.")
    assert client.patch(f"{API}/hospitals/{w['h2']}", headers=h["admin"], json={"is_active": False}).status_code == 200
    _err(_record(client, h["admin"], d["h2"]["id"], t), 400, message="Hospital is inactive; maintenance data cannot be added to it.")


def test_record_reads_are_scoped_and_filterable(client, tickets):
    h, d = tickets["h"], tickets["d"]
    t1, t2 = tickets["mtype"]("corrective"), tickets["mtype"]("inspection")
    tid = _in_progress_ticket(client, tickets)
    a = _record(client, h["tech_h1"], d["icu"]["id"], t1, ticket_id=tid).json()["id"]
    b = _record(client, h["eng_h1"], d["lab"]["id"], t2, description="Calibrated").json()["id"]
    c = _record(client, h["admin"], d["h2"]["id"], t1).json()["id"]
    ids = lambda who, **p: {r["id"] for r in client.get(f"{API}/maintenance-records", headers=h[who], params=p).json()["items"]}  # noqa: E731
    assert ids("tech_h1") == ids("eng_h1") == {a, b} and ids("eng_h2") == {c} and ids("admin") == {a, b, c}
    assert ids("admin", device_id=d["lab"]["id"]) == {b} and ids("admin", maintenance_type_id=t1) == {a, c}
    assert ids("admin", ticket_id=tid) == {a} and ids("admin", performed_by=tickets["world"]["tech_id"]) == {a}
    assert ids("admin", department_id=tickets["lab"]) == {b} and ids("tech_h1", hospital_id=tickets["world"]["h2"]) == set()
    now = datetime.now(timezone.utc)
    assert ids("admin", performed_from=(now - timedelta(hours=1)).isoformat()) == {a, b, c}
    assert ids("admin", performed_to=(now - timedelta(hours=1)).isoformat()) == set()
    r = client.get(f"{API}/maintenance-records", headers=h["admin"], params={"sort": "performed_at", "order": "asc", "page_size": 2})
    assert r.json()["total"] == 3 and [x["id"] for x in r.json()["items"]] == [a, b]
    for who in ("dept_icu", "dept_none"):
        _err(client.get(f"{API}/maintenance-records", headers=h[who]), 403)
        _err(client.get(f"{API}/maintenance-records/{a}", headers=h[who]), 403)
        _err(client.get(f"{API}/devices/{d['icu']['id']}/maintenance-records", headers=h[who]), 403)
    assert client.get(f"{API}/maintenance-records/{c}", headers=h["tech_h1"]).status_code == 404
    assert client.get(f"{API}/maintenance-records/{a}", headers=h["tech_h1"]).json()["description"] == "Replaced the power supply"
    hist = client.get(f"{API}/devices/{d['icu']['id']}/maintenance-records", headers=h["tech_h1"]).json()
    assert [x["id"] for x in hist["items"]] == [a]
    assert client.get(f"{API}/devices/{d['h2']['id']}/maintenance-records", headers=h["tech_h1"]).status_code == 404
    # archived devices keep a readable history (Decision 6)
    assert client.delete(f"{API}/devices/{d['lab']['id']}", headers=h["admin"]).status_code == 200
    hist = client.get(f"{API}/devices/{d['lab']['id']}/maintenance-records", headers=h["eng_h1"]).json()["items"]
    assert [x["id"] for x in hist] == [b] and hist[0]["device"]["is_archived"] is True


def test_record_corrections(client, tickets):
    h, d, sql = tickets["h"], tickets["d"], tickets["sql"]
    t = tickets["mtype"]("corrective")
    tid = _in_progress_ticket(client, tickets)
    rid = _record(client, h["tech_h1"], d["icu"]["id"], t, ticket_id=tid, description="Repalced fuse").json()["id"]
    audits = lambda: sql("SELECT count(*) FROM audit_logs WHERE record_id = :i", i=rid)[0][0]  # noqa: E731
    _err(client.patch(f"{API}/maintenance-records/{rid}", headers=h["tech_h1"], json={"description": "Replaced fuse"}), 403)
    _err(client.patch(f"{API}/maintenance-records/{rid}", headers=h["eng_h2"], json={"description": "x"}), 404)
    r = client.patch(f"{API}/maintenance-records/{rid}", headers=h["eng_h1"], json={"description": "Replaced fuse"})
    assert r.status_code == 200 and r.json()["description"] == "Replaced fuse" and audits() == 2
    assert client.patch(f"{API}/maintenance-records/{rid}", headers=h["admin"], json={"description": "Replaced fuse"}).status_code == 200
    assert audits() == 2                                                       # no-op: no audit row
    created = datetime.fromisoformat(client.get(f"{API}/tickets/{tid}", headers=h["admin"]).json()["created_at"])
    earlier = (created + timedelta(milliseconds=1)).isoformat()      # after the report, before now
    assert client.patch(f"{API}/maintenance-records/{rid}", headers=h["eng_h1"], json={"performed_at": earlier}).status_code == 200
    way_before = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    _err(client.patch(f"{API}/maintenance-records/{rid}", headers=h["eng_h1"], json={"performed_at": way_before}), 400)
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    _err(client.patch(f"{API}/maintenance-records/{rid}", headers=h["eng_h1"], json={"performed_at": future}), 400)
    for body in ({}, {"ticket_id": tid}, {"device_id": d["lab"]["id"]}, {"performed_by": tickets["world"]["admin_id"]}):
        assert client.patch(f"{API}/maintenance-records/{rid}", headers=h["eng_h1"], json=body).status_code == 422, body
    timeline = client.get(f"{API}/tickets/{tid}", headers=h["eng_h1"]).json()["timeline"]
    assert "Work performed: Replaced fuse" in [i["message"] for i in timeline]          # the timeline shows the correction
    p = tickets["mtype"]("preventive")
    sid = _schedule(client, h["eng_h1"], d["icu"]["id"], p, _today(tickets) + timedelta(days=5)).json()["id"]
    srid = _record(client, h["tech_h1"], d["icu"]["id"], p, schedule_id=sid).json()["id"]
    _err(client.patch(f"{API}/maintenance-records/{srid}", headers=h["eng_h1"], json={"performed_at": earlier}), 409,
         message="The work date of a scheduled maintenance record cannot be changed.")


# ---- schedules and devices.next_maintenance_due_date --------------------------------------------------
def test_schedules_drive_the_device_next_maintenance_date(client, tickets):
    h, d, sql = tickets["h"], tickets["d"], tickets["sql"]
    preventive, calibration = tickets["mtype"]("preventive"), tickets["mtype"]("calibration")
    today = _today(tickets)
    d1, d0 = today + timedelta(days=60), today + timedelta(days=20)
    a = _schedule(client, h["eng_h1"], d["icu"]["id"], preventive, d1, 90)
    assert a.status_code == 201 and a.json()["is_active"] and a.json()["last_performed_date"] is None
    a = a.json()["id"]
    assert _next_due(client, tickets, "icu") == str(d1)
    b = _schedule(client, h["admin"], d["icu"]["id"], calibration, d0, 365).json()["id"]
    assert _next_due(client, tickets, "icu") == str(d0)                                  # the earliest active one
    patch = lambda sid, who="eng_h1", **body: client.patch(f"{API}/maintenance-schedules/{sid}", headers=h[who], json=body)  # noqa: E731
    assert patch(b, is_active=False).json()["is_active"] is False
    assert _next_due(client, tickets, "icu") == str(d1)
    assert patch(a, next_due_date=str(today + timedelta(days=7))).status_code == 200
    assert _next_due(client, tickets, "icu") == str(today + timedelta(days=7))
    assert patch(a, is_active=False).status_code == 200
    assert _next_due(client, tickets, "icu") is None                                      # no active schedule
    assert patch(b, is_active=True).status_code == 200
    assert _next_due(client, tickets, "icu") == str(d0)
    changes = sql("SELECT old_values->>'next_maintenance_due_date', new_values->>'next_maintenance_due_date' FROM audit_logs "
                  "WHERE table_name = 'devices' AND record_id = :i AND action = 'update' AND new_values ? 'next_maintenance_due_date' "
                  "ORDER BY created_at",
                  i=d["icu"]["id"])
    assert [c[1] for c in changes] == [str(d1), str(d0), str(d1), str(today + timedelta(days=7)), None, str(d0)]
    n = len(changes)
    assert patch(a, frequency_days=30).status_code == 200                                 # inactive: date unchanged
    assert len(sql("SELECT 1 FROM audit_logs WHERE table_name = 'devices' AND record_id = :i AND action = 'update' "
                   "AND new_values ? 'next_maintenance_due_date'", i=d["icu"]["id"])) == n
    assert patch(a, frequency_days=30).status_code == 200                                 # no-op

    _err(_schedule(client, h["eng_h1"], d["icu"]["id"], preventive, d1), 409,
         message="This device already has a schedule for this maintenance type.")
    _err(_schedule(client, h["tech_h1"], d["lab"]["id"], preventive, d1), 403)
    _err(_schedule(client, h["dept_icu"], d["icu"]["id"], calibration, d1), 403)
    _err(_schedule(client, h["eng_h1"], d["h2"]["id"], preventive, d1), 404)
    _err(_schedule(client, h["eng_h1"], d["archived"]["id"], preventive, d1), 400)
    _err(_schedule(client, h["eng_h1"], d["lab"]["id"], str(uuid.uuid4()), d1), 400, message="Unknown maintenance type.")
    _err(patch(a, who="tech_h1", frequency_days=10), 403)
    _err(patch(a, who="eng_h2", frequency_days=10), 404)
    for body in ({}, {"frequency_days": 0}, {"is_active": None}, {"device_id": d["lab"]["id"]}, {"last_performed_date": str(today)}):
        assert client.patch(f"{API}/maintenance-schedules/{a}", headers=h["eng_h1"], json=body).status_code == 422, body
    assert client.post(f"{API}/maintenance-schedules", headers=h["eng_h1"],
                       json={"device_id": d["lab"]["id"], "maintenance_type_id": preventive, "frequency_days": 0,
                             "next_due_date": str(d1)}).status_code == 422


def test_preventive_record_moves_the_schedule_forward_never_backward(client, tickets):
    h, d = tickets["h"], tickets["d"]
    preventive, other = tickets["mtype"]("preventive"), tickets["mtype"]("inspection")
    today = _today(tickets)
    sid = _schedule(client, h["eng_h1"], d["icu"]["id"], preventive, today + timedelta(days=3), 30).json()["id"]
    r = _record(client, h["tech_h1"], d["icu"]["id"], preventive, schedule_id=sid, description="Quarterly service")
    assert r.status_code == 201 and r.json()["schedule_id"] == sid
    s = client.get(f"{API}/maintenance-schedules/{sid}", headers=h["tech_h1"]).json()
    assert s["last_performed_date"] == str(today) and s["next_due_date"] == str(today + timedelta(days=30))
    assert _next_due(client, tickets, "icu") == str(today + timedelta(days=30))
    # a backdated record is history only: the schedule does not move back
    old = (datetime.now(timezone.utc) - timedelta(days=60)).isoformat()
    assert _record(client, h["tech_h1"], d["icu"]["id"], preventive, schedule_id=sid, performed_at=old).status_code == 201
    s = client.get(f"{API}/maintenance-schedules/{sid}", headers=h["tech_h1"]).json()
    assert s["last_performed_date"] == str(today) and s["next_due_date"] == str(today + timedelta(days=30))
    _err(_record(client, h["tech_h1"], d["icu"]["id"], other, schedule_id=sid), 400,
         message="The schedule does not exist or belongs to another device or maintenance type.")
    _err(_record(client, h["tech_h1"], d["lab"]["id"], preventive, schedule_id=sid), 400)
    _err(_record(client, h["tech_h1"], d["icu"]["id"], preventive, schedule_id=str(uuid.uuid4())), 400)
    assert client.patch(f"{API}/maintenance-schedules/{sid}", headers=h["eng_h1"], json={"is_active": False}).status_code == 200
    _err(_record(client, h["tech_h1"], d["icu"]["id"], preventive, schedule_id=sid), 400,
         message="Inactive schedules cannot receive maintenance records.")


def test_due_and_overdue_lists(client, tickets):
    h, d = tickets["h"], tickets["d"]
    p, c = tickets["mtype"]("preventive"), tickets["mtype"]("calibration")
    today = _today(tickets)
    overdue = _schedule(client, h["eng_h1"], d["icu"]["id"], p, today - timedelta(days=3)).json()
    soon = _schedule(client, h["eng_h1"], d["lab"]["id"], p, today + timedelta(days=5)).json()
    later = _schedule(client, h["eng_h1"], d["icu"]["id"], c, today + timedelta(days=200)).json()
    h2 = _schedule(client, h["admin"], d["h2"]["id"], p, today).json()
    lst = lambda who, **q: client.get(f"{API}/maintenance-schedules", headers=h[who], params=q).json()["items"]  # noqa: E731
    assert [s["id"] for s in lst("tech_h1")] == [overdue["id"], soon["id"], later["id"]]   # soonest first, own hospital
    assert overdue["is_overdue"] is True and soon["is_overdue"] is False and h2["is_overdue"] is False
    assert [s["id"] for s in lst("tech_h1", overdue=True)] == [overdue["id"]]
    assert [s["id"] for s in lst("tech_h1", due_before=str(today + timedelta(days=5)))] == [overdue["id"], soon["id"]]
    assert [s["id"] for s in lst("tech_h1", department_id=tickets["lab"])] == [soon["id"]]
    assert {s["id"] for s in lst("admin")} == {overdue["id"], soon["id"], later["id"], h2["id"]}
    assert [s["id"] for s in lst("eng_h2")] == [h2["id"]]
    assert client.get(f"{API}/maintenance-schedules/{h2['id']}", headers=h["tech_h1"]).status_code == 404
    for who in ("dept_icu", "dept_none"):
        _err(client.get(f"{API}/maintenance-schedules", headers=h[who]), 403)
        _err(client.get(f"{API}/devices/{d['icu']['id']}/maintenance-schedules", headers=h[who]), 403)
    # inactive and archived-device schedules leave the due lists, but stay on the device
    assert client.patch(f"{API}/maintenance-schedules/{later['id']}", headers=h["eng_h1"], json={"is_active": False}).status_code == 200
    assert client.delete(f"{API}/devices/{d['lab']['id']}", headers=h["admin"]).status_code == 200
    assert [s["id"] for s in lst("tech_h1")] == [overdue["id"]]
    assert {s["id"] for s in lst("tech_h1", include_inactive=True)} == {overdue["id"], later["id"]}
    on_device = client.get(f"{API}/devices/{d['icu']['id']}/maintenance-schedules", headers=h["tech_h1"]).json()["items"]
    assert [s["id"] for s in on_device] == [overdue["id"], later["id"]]
    archived = client.get(f"{API}/devices/{d['lab']['id']}/maintenance-schedules", headers=h["tech_h1"]).json()["items"]
    assert [s["id"] for s in archived] == [soon["id"]] and archived[0]["device"]["is_archived"] is True
    # schedules of an archived device can only be deactivated
    _err(client.patch(f"{API}/maintenance-schedules/{soon['id']}", headers=h["eng_h1"], json={"frequency_days": 10}), 400,
         message="Schedules of archived devices can only be deactivated.")
    assert client.patch(f"{API}/maintenance-schedules/{soon['id']}", headers=h["eng_h1"], json={"is_active": False}).status_code == 200


def test_maintenance_types(client, tickets):
    h = tickets["h"]
    tid = tickets["mtype"]("  Corrective")
    names = {t["id"]: t["name"] for t in client.get(f"{API}/maintenance-types", headers=h["tech_h1"]).json()}
    assert names[tid] == f"corrective-{tickets['world']['sfx']}"                       # trimmed, lower-cased
    _err(client.post(f"{API}/maintenance-types", headers=h["admin"], json={"name": f"CORRECTIVE-{tickets['world']['sfx']}"}), 409,
         message="A maintenance type with this name already exists.")
    for who in ("eng_h1", "tech_h1", "dept_icu"):
        _err(client.post(f"{API}/maintenance-types", headers=h[who], json={"name": "x"}), 403)
    for who in ("dept_icu", "dept_none"):
        _err(client.get(f"{API}/maintenance-types", headers=h[who]), 403)
    for body in ({"name": ""}, {"name": "x" * 51}, {}):
        assert client.post(f"{API}/maintenance-types", headers=h["admin"], json=body).status_code == 422
    rows = tickets["sql"]("SELECT action::text, organization_id::text FROM audit_logs WHERE record_id = :i", i=tid)
    assert rows == [("insert", tickets["world"]["org"])]


def test_maintenance_endpoints_require_authentication_and_are_documented(client):
    for method, url in (("get", "/maintenance-types"), ("post", "/maintenance-types"), ("get", "/maintenance-records"),
                        ("post", "/maintenance-records"), ("get", f"/maintenance-records/{uuid.uuid4()}"),
                        ("patch", f"/maintenance-records/{uuid.uuid4()}"), ("get", "/maintenance-schedules"),
                        ("post", "/maintenance-schedules"), ("patch", f"/maintenance-schedules/{uuid.uuid4()}"),
                        ("get", f"/devices/{uuid.uuid4()}/maintenance-records"), ("get", f"/devices/{uuid.uuid4()}/maintenance-schedules")):
        assert getattr(client, method)(f"{API}{url}").status_code == 401, url
    paths = client.get("/openapi.json").json()["paths"]
    assert set(paths[f"{API}/maintenance-records"]) == {"get", "post"} == set(paths[f"{API}/maintenance-schedules"])
    assert set(paths[f"{API}/maintenance-records/{{record_id}}"]) == {"get", "patch"}
    assert set(paths[f"{API}/maintenance-schedules/{{schedule_id}}"]) == {"get", "patch"}
    assert set(paths[f"{API}/maintenance-types"]) == {"get", "post"}


# ---- concurrency ---------------------------------------------------------------------------------------
def _race(client, lock_sql, params, calls):
    """Hold a row lock in another transaction, start the calls in parallel, check they WAIT, release."""
    results = [None] * len(calls)
    with get_session_factory()() as holder:
        holder.execute(text(lock_sql), params)

        def run(i, call):
            with TestClient(client.app) as c:
                results[i] = call(c)

        threads = [threading.Thread(target=run, args=(i, call)) for i, call in enumerate(calls)]
        for t in threads:
            t.start()
        time.sleep(1.0)
        blocked = [t.is_alive() for t in threads]
        holder.rollback()
    for t in threads:
        t.join(timeout=30)
    assert blocked == [True] * len(calls), "requests did not wait for the row lock"
    return results


def test_concurrent_schedule_changes_leave_the_device_date_correct(client, tickets):
    """Two schedules of one device changed at the same moment: without the device lock each would
    compute the minimum from the other's OLD date and the device could keep a stale value."""
    h, d, sql = tickets["h"], tickets["d"], tickets["sql"]
    today = _today(tickets)
    a = _schedule(client, h["eng_h1"], d["icu"]["id"], tickets["mtype"]("preventive"), today + timedelta(days=50)).json()["id"]
    b = _schedule(client, h["eng_h1"], d["icu"]["id"], tickets["mtype"]("calibration"), today + timedelta(days=40)).json()["id"]
    x, y = today + timedelta(days=90), today + timedelta(days=70)
    results = _race(client, "SELECT id FROM devices WHERE id = :d FOR UPDATE", {"d": d["icu"]["id"]}, [
        lambda c: c.patch(f"{API}/maintenance-schedules/{a}", headers=h["eng_h1"], json={"next_due_date": str(x)}),
        lambda c: c.patch(f"{API}/maintenance-schedules/{b}", headers=h["admin"], json={"next_due_date": str(y)}),
    ])
    assert [r.status_code for r in results] == [200, 200]
    expected = sql("SELECT min(next_due_date) FROM maintenance_schedules WHERE device_id = :d AND is_active", d=d["icu"]["id"])[0][0]
    assert expected == y and _next_due(client, tickets, "icu") == str(y)


def test_record_and_cancel_racing_on_one_ticket_never_leave_work_on_a_cancelled_ticket(client, tickets):
    h, d = tickets["h"], tickets["d"]
    t = tickets["mtype"]("corrective")
    tid = _in_progress_ticket(client, tickets)
    results = _race(client, "SELECT id FROM maintenance_tickets WHERE id = :t FOR UPDATE", {"t": tid}, [
        lambda c: _record(c, h["tech_h1"], d["icu"]["id"], t, ticket_id=tid),
        lambda c: _status(c, h["eng_h1"], tid, "cancelled"),
    ])
    record, cancel = results
    assert cancel.status_code == 200
    assert record.status_code in (201, 409), record.text
    if record.status_code == 409:
        assert record.json()["error"]["message"] == "Closed or cancelled tickets cannot receive maintenance records."
    rows = tickets["sql"]("SELECT r.created_at <= (SELECT max(created_at) FROM audit_logs WHERE record_id = :t "
                          "AND new_values->>'status' = 'cancelled') FROM maintenance_records r WHERE r.ticket_id = :t", t=tid)
    assert all(ok for (ok,) in rows)  # any record was written before the cancellation, never after
