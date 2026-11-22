"""B4 CP1 - ticket core against REAL PostgreSQL: reporting a problem (incl. the approved QR
exception), visibility per role, device ticket history, soft-deleted tickets, filters, the derived
timeline and its privacy rules. Skipped unless TEST_DATABASE_URL is set; everything created here
is removed again (tests/ticket_scene.py).

Scene (tests/scope_scene.py): H1 = ICU + Lab, H2 = Radiology. Devices icu, lab (H1), h2 (H2),
archived (H1/ICU). Users: dept_icu, dept_none, tech_h1, eng_h1, eng_h2, tech_h2, admin.
"""
import re
import uuid
from datetime import datetime, timedelta, timezone

from tests.scope_scene import scene  # noqa: F401
from tests.test_devices_flow import cat  # noqa: F401
from tests.ticket_scene import tickets  # noqa: F401
from tests.world import API

NUMBER = re.compile(r"^TKT-[0-9A-F]{8}$")


def _me(client, headers):
    return client.get(f"{API}/auth/me", headers=headers).json()["id"]


def _ids(response):
    assert response.status_code == 200, response.text
    return {t["id"] for t in response.json()["items"]}


# ---- reporting a problem ------------------------------------------------------------------------
def test_department_user_reports_a_problem_on_their_own_device(client, tickets):
    h, d = tickets["h"], tickets["d"]
    me = _me(client, h["dept_icu"])
    r = tickets["report"](h["dept_icu"], "icu", description="  The device won't turn on  ")
    assert r.status_code == 201, r.text
    t = r.json()
    assert NUMBER.match(t["number"]) and t["number"] == "TKT-" + t["id"].replace("-", "")[:8].upper()
    assert (t["status"], t["priority"], t["category"], t["description"]) == ("open", "medium", "Power issue", "The device won't turn on")
    assert t["device"] == {"id": d["icu"]["id"], "device_code": "S-ICU", "name": "ICU ventilator",
                           "department_id": tickets["world"]["icu"], "department_name": "ICU"}
    assert t["hospital_id"] == tickets["world"]["h1"] and t["reported_by"]["id"] == me
    assert t["assignees"] == [] and t["is_deleted"] is False and t["resolved_at"] is None
    assert [(i["kind"], i["status"], i["message"]) for i in t["timeline"]] == [("created", "open", "Ticket created.")]
    assert t["timeline"][0]["actor"] == t["reported_by"]["name"]

    row = tickets["sql"]("SELECT organization_id::text, hospital_id::text, reported_by::text, problem_description, "
                         "status::text, priority::text, xmin::text FROM maintenance_tickets WHERE id = :i", i=t["id"])[0]
    assert row[:6] == (tickets["world"]["org"], tickets["world"]["h1"], me, "[Power issue] The device won't turn on", "open", "medium")
    audit = tickets["sql"]("SELECT action::text, user_id::text, new_values->>'status', new_values->>'problem_description', xmin::text "
                           "FROM audit_logs WHERE table_name = 'maintenance_tickets' AND record_id = :i", i=t["id"])
    assert len(audit) == 1 and audit[0][:4] == ("insert", me, "open", "[Power issue] The device won't turn on")
    assert audit[0][4] == row[6], "ticket and audit row must be written in the same transaction"


def test_every_category_and_priority_is_stored_as_the_mobile_app_expects(client, tickets):
    h = tickets["h"]
    for label in ("Device not working", "Abnormal reading", "Physical damage", "Alarm/problem", "Power issue", "Other"):
        r = tickets["report"](h["tech_h1"], "icu", category=label, description=f"about {label}")
        assert r.status_code == 201 and (r.json()["category"], r.json()["description"]) == (label, f"about {label}")
        stored = tickets["sql"]("SELECT problem_description FROM maintenance_tickets WHERE id = :i", i=r.json()["id"])[0][0]
        assert stored == f"[{label}] about {label}"
    assert tickets["report"](h["tech_h1"], "icu", priority=None).json()["priority"] == "medium"
    assert tickets["report"](h["tech_h1"], "icu", priority="critical").json()["priority"] == "critical"


def test_department_user_reports_on_another_department_via_qr_without_gaining_device_access(client, tickets):
    """Approved QR exception: report a problem on another department's device of the same hospital,
    without seeing its internals, its other tickets or its device record."""
    h, lab = tickets["h"], tickets["d"]["lab"]
    scanned = client.get(f"{API}/devices/qr/{lab['qr_identifier']}", headers=h["dept_icu"]).json()
    assert scanned["access"] == "limited"
    r = tickets["report"](h["dept_icu"], scanned["id"], category="Alarm/problem", description="Alarm keeps sounding")
    assert r.status_code == 201, r.text
    t = r.json()
    assert t["device"]["department_name"] == "Lab" and "SN-SECRET-2" not in r.text and "criticality" not in r.text
    detail = client.get(f"{API}/tickets/{t['id']}", headers=h["dept_icu"])
    assert detail.status_code == 200 and "SN-SECRET-2" not in detail.text
    other = tickets["report"](h["tech_h1"], "lab").json()
    assert client.get(f"{API}/devices/{lab['id']}/tickets", headers=h["dept_icu"]).status_code == 404
    assert client.get(f"{API}/tickets/{other['id']}", headers=h["dept_icu"]).status_code == 404
    assert client.get(f"{API}/devices/{lab['id']}", headers=h["dept_icu"]).status_code == 404  # CP3 unchanged


def test_reporting_scope_per_role(client, tickets):
    h, report = tickets["h"], tickets["report"]
    expected = {
        ("dept_icu", "h2"): 404, ("tech_h1", "h2"): 404, ("eng_h1", "h2"): 404,
        ("eng_h2", "h2"): 201, ("tech_h2", "h2"): 201, ("admin", "h2"): 201,
        ("eng_h1", "lab"): 201, ("tech_h2", "icu"): 404,
    }
    for (who, device), status in expected.items():
        assert report(h[who], device).status_code == status, (who, device)
    r = report(h["dept_none"], "icu")
    assert r.status_code == 403 and r.json()["error"]["code"] == "department_required"
    r = report(h["admin"], str(uuid.uuid4()))
    assert r.status_code == 404 and r.json()["error"]["message"] == "Device not found."


def test_archived_devices_and_inactive_hospitals_cannot_receive_tickets(client, tickets):
    h = tickets["h"]
    before = tickets["sql"]("SELECT count(*) FROM maintenance_tickets WHERE organization_id = :o", o=tickets["world"]["org"])[0][0]
    r = tickets["report"](h["dept_icu"], "archived")
    assert r.status_code == 400 and r.json()["error"]["message"] == "Archived devices cannot receive new tickets."
    assert client.patch(f"{API}/hospitals/{tickets['world']['h2']}", headers=h["admin"], json={"is_active": False}).status_code == 200
    r = tickets["report"](h["admin"], "h2")
    assert r.status_code == 400 and r.json()["error"]["message"] == "Hospital is inactive; tickets cannot be added to it."
    after = tickets["sql"]("SELECT count(*) FROM maintenance_tickets WHERE organization_id = :o", o=tickets["world"]["org"])[0][0]
    assert after == before


def test_invalid_requests_are_rejected_and_create_nothing(client, tickets):
    h, icu = tickets["h"], tickets["d"]["icu"]["id"]
    bad = [
        {"device_id": icu, "description": "x"},                                       # no category
        {"device_id": icu, "category": "Broken", "description": "x"},
        {"device_id": icu, "category": "Other", "description": "   "},
        {"device_id": icu, "category": "Other", "description": "x" * 2001},
        {"device_id": icu, "category": "Other", "description": "x", "priority": "urgent"},
        {"device_id": icu, "category": "Other", "description": "x", "status": "closed"},
        {"device_id": icu, "category": "Other", "description": "x", "reported_by": tickets["world"]["admin_id"]},
        {"device_id": "nope", "category": "Other", "description": "x"},
    ]
    for body in bad:
        r = client.post(f"{API}/tickets", headers=h["admin"], json=body)
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error", body
    assert tickets["sql"]("SELECT count(*) FROM maintenance_tickets WHERE organization_id = :o", o=tickets["world"]["org"])[0][0] == 0


def test_ticket_endpoints_require_authentication(client, tickets):
    tid = tickets["report"](tickets["h"]["tech_h1"], "icu").json()["id"]
    for method, url in (("post", "/tickets"), ("get", "/tickets"), ("get", "/tickets/mine"), ("get", f"/tickets/{tid}"),
                        ("get", f"/devices/{tickets['d']['icu']['id']}/tickets")):
        assert getattr(client, method)(f"{API}{url}").status_code == 401, url


# ---- visibility ---------------------------------------------------------------------------------
def test_visibility_matrix_lists_details_and_mine(client, tickets):
    h, report = tickets["h"], tickets["report"]
    h["colleague"] = tickets["add_user"]("dept-icu-2", "department_user", "h1", tickets["world"]["icu"])
    t = {
        "icu": report(h["dept_icu"], "icu").json()["id"],
        "colleague": report(h["colleague"], "icu").json()["id"],
        "lab": report(h["tech_h1"], "lab").json()["id"],
        "h2": report(h["eng_h2"], "h2").json()["id"],
    }
    h1 = {t["icu"], t["colleague"], t["lab"]}
    visible = {
        "dept_icu": {t["icu"]}, "colleague": {t["colleague"]}, "dept_none": set(),
        "tech_h1": h1, "eng_h1": h1, "eng_h2": {t["h2"]}, "tech_h2": {t["h2"]}, "admin": set(t.values()),
    }
    reported = {"dept_icu": {t["icu"]}, "colleague": {t["colleague"]}, "tech_h1": {t["lab"]}, "eng_h2": {t["h2"]}}
    for who, ids in visible.items():
        assert _ids(client.get(f"{API}/tickets", headers=h[who])) == ids, who
        assert _ids(client.get(f"{API}/tickets/mine", headers=h[who])) == reported.get(who, set()), who
        for tid in t.values():
            expected = 200 if tid in ids else 404
            assert client.get(f"{API}/tickets/{tid}", headers=h[who]).status_code == expected, (who, tid)
    r = client.get(f"{API}/tickets/{uuid.uuid4()}", headers=h["admin"])
    assert r.status_code == 404 and r.json()["error"]["message"] == "Ticket not found."


def test_staff_keep_seeing_their_own_reports_after_moving_hospital(client, tickets):
    h = tickets["h"]
    own = tickets["report"](h["tech_h1"], "lab").json()["id"]
    other_h1 = tickets["report"](h["eng_h1"], "icu").json()["id"]
    h2_ticket = tickets["report"](h["eng_h2"], "h2").json()["id"]
    tickets["sql"]("UPDATE users SET hospital_id = :h WHERE email = :e", h=tickets["world"]["h2"], e=tickets["world"]["tech"])
    assert _ids(client.get(f"{API}/tickets", headers=h["tech_h1"])) == {own, h2_ticket}
    assert client.get(f"{API}/tickets/{other_h1}", headers=h["tech_h1"]).status_code == 404


def test_device_history_department_users_see_only_their_own_tickets(client, tickets):
    """Approved decision Q3."""
    h, report, icu = tickets["h"], tickets["report"], tickets["d"]["icu"]["id"]
    h["colleague"] = tickets["add_user"]("dept-icu-3", "department_user", "h1", tickets["world"]["icu"])
    mine = report(h["dept_icu"], "icu").json()["id"]
    theirs = report(h["colleague"], "icu").json()["id"]
    staff = report(h["tech_h1"], "icu").json()["id"]
    report(h["tech_h1"], "lab")
    url = f"{API}/devices/{icu}/tickets"
    assert _ids(client.get(url, headers=h["dept_icu"])) == {mine}
    assert _ids(client.get(url, headers=h["tech_h1"])) == {mine, theirs, staff}
    assert _ids(client.get(url, headers=h["admin"])) == {mine, theirs, staff}
    assert _ids(client.get(url, headers=h["tech_h1"], params={"status": "resolved"})) == set()
    r = client.get(url, headers=h["dept_none"])
    assert r.status_code == 403 and r.json()["error"]["code"] == "department_required"
    assert client.get(url, headers=h["tech_h2"]).status_code == 404
    assert client.get(f"{API}/devices/{uuid.uuid4()}/tickets", headers=h["admin"]).status_code == 404
    # archived devices keep a readable history (Decision 6)
    assert client.get(f"{API}/devices/{tickets['d']['archived']['id']}/tickets", headers=h["tech_h1"]).status_code == 200


def test_department_user_without_department_keeps_their_own_tickets(client, tickets):
    """Approved decision Q11: read access to own reports stays; reporting is blocked."""
    h = tickets["h"]
    tid = tickets["report"](h["dept_icu"], "icu").json()["id"]
    tickets["sql"]("UPDATE users SET department_id = NULL WHERE email = :e", e=tickets["world"]["staff"])
    assert _ids(client.get(f"{API}/tickets/mine", headers=h["dept_icu"])) == {tid}
    assert _ids(client.get(f"{API}/tickets", headers=h["dept_icu"])) == {tid}
    assert client.get(f"{API}/tickets/{tid}", headers=h["dept_icu"]).status_code == 200
    for r in (tickets["report"](h["dept_icu"], "icu"),
              client.get(f"{API}/devices/{tickets['d']['icu']['id']}/tickets", headers=h["dept_icu"])):
        assert r.status_code == 403 and r.json()["error"]["code"] == "department_required"


def test_soft_deleted_tickets_are_admin_only(client, tickets):
    """Decision 6: deleted tickets are hidden except in admin (and audit) views."""
    h = tickets["h"]
    gone = tickets["report"](h["dept_icu"], "icu").json()["id"]
    kept = tickets["report"](h["dept_icu"], "icu").json()["id"]
    tickets["sql"]("UPDATE maintenance_tickets SET deleted_at = now() WHERE id = :i", i=gone)
    for who in ("dept_icu", "tech_h1"):
        assert client.get(f"{API}/tickets/{gone}", headers=h[who]).status_code == 404
        assert _ids(client.get(f"{API}/tickets", headers=h[who])) == {kept}
        r = client.get(f"{API}/tickets", headers=h[who], params={"include_deleted": True})
        assert r.status_code == 403 and r.json()["error"]["message"] == "Only administrators can include deleted tickets."
    assert _ids(client.get(f"{API}/tickets/mine", headers=h["dept_icu"])) == {kept}
    assert _ids(client.get(f"{API}/tickets", headers=h["admin"])) == {kept}
    r = client.get(f"{API}/tickets", headers=h["admin"], params={"include_deleted": True})
    assert _ids(r) == {gone, kept} and {t["id"]: t["is_deleted"] for t in r.json()["items"]}[gone] is True
    detail = client.get(f"{API}/tickets/{gone}", headers=h["admin"])
    assert detail.status_code == 200 and detail.json()["is_deleted"] is True


# ---- filters, search, sort, pagination ------------------------------------------------------------
def test_filters_search_sort_and_pagination(client, tickets):
    h, report, sql = tickets["h"], tickets["report"], tickets["sql"]
    a = report(h["dept_icu"], "icu", category="Power issue", description="Screen flickers", priority="low").json()["id"]
    b = report(h["tech_h1"], "lab", category="Abnormal reading", description="Reading 100% off", priority="critical").json()["id"]
    c = report(h["eng_h1"], "icu", category="Other", description="Loose cable", priority="high").json()["id"]
    sql("UPDATE maintenance_tickets SET status = 'in_progress' WHERE id = :i", i=c)
    tech_id = tickets["world"]["tech_id"]
    sql("INSERT INTO ticket_assignments (ticket_id, user_id) VALUES (:t, :u)", t=a, u=tech_id)
    sql("INSERT INTO ticket_assignments (ticket_id, user_id, assigned_at, unassigned_at) "
        "VALUES (:t, :u, now() - interval '1 hour', now())", t=b, u=tech_id)  # no longer assigned
    get = lambda **p: _ids(client.get(f"{API}/tickets", headers=h["eng_h1"], params=p))  # noqa: E731

    assert get() == {a, b, c}
    assert get(status="open") == {a, b} and get(status=["open", "in_progress"]) == {a, b, c}
    assert get(priority=["low", "critical"]) == {a, b}
    assert get(device_id=tickets["d"]["lab"]["id"]) == {b}
    assert get(department_id=tickets["lab"]) == {b} and get(department_id=tickets["world"]["icu"]) == {a, c}
    assert get(reported_by=tickets["world"]["tech_id"]) == {b}
    assert get(assigned_to=tech_id) == {a}
    assert _ids(client.get(f"{API}/tickets", headers=h["tech_h1"], params={"assigned_to": "me"})) == {a}
    assert get(q="flicker") == {a} and get(q="s-lab") == {b} and get(q="100%") == {b} and get(q="%") == {b}
    assert get(q="_") == set()  # LIKE wildcards are matched literally
    now = datetime.now(timezone.utc)
    assert get(created_from=(now - timedelta(hours=1)).isoformat()) == {a, b, c}
    assert get(created_from=(now + timedelta(hours=1)).isoformat()) == set()
    assert get(created_to=(now - timedelta(hours=1)).isoformat()) == set()
    assert get(hospital_id=tickets["world"]["h2"]) == set()  # filters only narrow the scope

    r = client.get(f"{API}/tickets", headers=h["eng_h1"], params={"sort": "priority", "order": "desc"})
    assert [t["id"] for t in r.json()["items"]] == [b, c, a]
    r = client.get(f"{API}/tickets", headers=h["eng_h1"], params={"page": 2, "page_size": 2})
    assert r.json()["total"] == 3 and len(r.json()["items"]) == 1 and r.json()["page"] == 2
    for params in ({"assigned_to": "someone"}, {"status": "broken"}, {"sort": "device"}, {"page_size": 101}):
        assert client.get(f"{API}/tickets", headers=h["eng_h1"], params=params).status_code == 422, params


# ---- timeline, assignees and privacy ----------------------------------------------------------------
def test_assignees_and_timeline_show_names_to_staff_and_roles_to_department_users(client, tickets):
    h, sql, w = tickets["h"], tickets["sql"], tickets["world"]
    tid = tickets["report"](h["dept_icu"], "icu").json()["id"]
    eng_id = _me(client, h["eng_h1"])
    sql("INSERT INTO ticket_assignments (ticket_id, user_id) VALUES (:t, :u)", t=tid, u=w["tech_id"])
    for minutes, user, new, old in ((1, eng_id, '{"priority": "high"}', '{"priority": "medium"}'),
                                    (2, w["tech_id"], '{"status": "in_progress"}', '{"status": "open"}')):
        sql("INSERT INTO audit_logs (organization_id, user_id, table_name, record_id, action, old_values, new_values, created_at) "
            "VALUES (:o, :u, 'maintenance_tickets', :r, 'update', CAST(:old AS jsonb), CAST(:new AS jsonb), "
            "now() + make_interval(mins => :m))", o=w["org"], u=user, r=tid, old=old, new=new, m=minutes)

    staff = client.get(f"{API}/tickets/{tid}", headers=h["eng_h1"]).json()
    assert [(a["id"], a["role"]) for a in staff["assignees"]] == [(w["tech_id"], "technician")]
    assert staff["assignees"][0]["name"] == w["tech"].split("@")[0]
    assert [(i["kind"], i["status"]) for i in staff["timeline"]] == [
        ("created", "open"), ("priority_changed", "open"), ("status_changed", "in_progress")]
    assert staff["timeline"][1]["message"] == "Priority changed from Medium to High."
    assert staff["timeline"][2]["actor"] == w["tech"].split("@")[0]

    own = client.get(f"{API}/tickets/{tid}", headers=h["dept_icu"]).json()
    assert own["assignees"] == [{"id": None, "name": "Technician", "role": "technician",
                                 "assigned_at": own["assignees"][0]["assigned_at"]}]
    assert [i["actor"] for i in own["timeline"]] == [own["reported_by"]["name"], "Biomedical engineer", "Technician"]
    assert w["tech"].split("@")[0] not in client.get(f"{API}/tickets/mine", headers=h["dept_icu"]).text


def test_ticket_created_outside_the_backend_reads_like_the_seeded_ticket(client, tickets):
    """Seeds and legacy data: no '[Category]' prefix and no INSERT audit row."""
    h, sql, w = tickets["h"], tickets["sql"], tickets["world"]
    tid = sql("INSERT INTO maintenance_tickets (organization_id, hospital_id, device_id, reported_by, problem_description, "
              "priority, status, resolved_at, created_at) VALUES (:o, :h, :d, :u, 'Abnormal pressure reading on the display.', "
              "'high', 'resolved', now(), now() - interval '2 days') RETURNING id::text",
              o=w["org"], h=w["h1"], d=tickets["d"]["icu"]["id"], u=w["tech_id"])[0][0]
    sql("INSERT INTO audit_logs (organization_id, user_id, table_name, record_id, action, new_values) "
        "VALUES (:o, :u, 'maintenance_tickets', :r, 'update', '{\"status\": \"resolved\"}')", o=w["org"], u=w["tech_id"], r=tid)
    t = client.get(f"{API}/tickets/{tid}", headers=h["eng_h1"]).json()
    assert (t["category"], t["description"]) == ("Other", "Abnormal pressure reading on the display.")
    assert t["status"] == "resolved" and t["resolved_at"] is not None
    assert [(i["kind"], i["status"]) for i in t["timeline"]] == [("created", "open"), ("status_changed", "resolved")]
    assert t["timeline"][0]["actor"] == w["tech"].split("@")[0]


def test_mobile_flow_scan_report_and_follow(client, tickets):
    """login -> scan QR -> report -> my tickets -> ticket detail (mobile MVP flow)."""
    h, icu = tickets["h"], tickets["d"]["icu"]
    device = client.get(f"{API}/devices/qr/{icu['qr_identifier'].lower()}", headers=h["dept_icu"]).json()
    created = tickets["report"](h["dept_icu"], device["id"], category="Device not working", description="No power").json()
    mine = client.get(f"{API}/tickets/mine", headers=h["dept_icu"]).json()
    assert mine["total"] == 1 and mine["items"][0]["number"] == created["number"]
    assert mine["items"][0]["device"]["name"] == device["name"] and "timeline" not in mine["items"][0]
    detail = client.get(f"{API}/tickets/{created['id']}", headers=h["dept_icu"]).json()
    assert detail["number"] == created["number"] and detail["timeline"][0]["kind"] == "created"


def test_openapi_documents_the_ticket_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert set(paths[f"{API}/tickets"]) == {"get", "post"}
    for p in (f"{API}/tickets/mine", f"{API}/tickets/{{ticket_id}}", f"{API}/devices/{{device_id}}/tickets"):
        assert set(paths[p]) == {"get"}, p
