"""B6 CP1 - risk assessments against REAL PostgreSQL: permissions in the approved order (role first,
then existence/scope, then device state), the trigger-maintained devices.current_risk_level, dates
(D6), equal times (D7), device and hospital states (D8, D9), trusted fields (D4b), audit in the same
transaction including the device-cache row (D17), filters, sorting and paging.
Skipped unless TEST_DATABASE_URL is set; everything created here is removed (tests/risk_scene.py).
"""
import uuid
from datetime import datetime, timedelta, timezone

from tests.risk_scene import rq  # noqa: F401
from tests.scope_scene import scene  # noqa: F401
from tests.test_devices_flow import cat  # noqa: F401
from tests.ticket_scene import tickets  # noqa: F401
from tests.world import API

T1, T2, T3 = "2026-03-01T10:00:00+00:00", "2026-06-01T10:00:00+00:00", "2026-09-01T10:00:00+00:00"


def _err(r, status, code=None, message=None):
    assert r.status_code == status, r.text
    if code:
        assert r.json()["error"]["code"] == code, r.text
    if message:
        assert r.json()["error"]["message"] == message, r.text


def _same_instant(a, b):
    return datetime.fromisoformat(a) == datetime.fromisoformat(b)


# ---- permissions, in the approved order -------------------------------------------------------------
def test_unauthorized_roles_get_403_before_any_lookup(client, rq):
    """Technicians and department users may not write: 403 even for an unknown or other-hospital id
    (no lookup happens), never 404 - so the response reveals nothing about what exists."""
    h, d = rq["h"], rq["d"]
    existing = rq["assess"](h["eng_h1"], "icu", "high", assessed_at=T1).json()["id"]
    h2_assessment = rq["assess"](h["admin"], "h2", "low", assessed_at=T1).json()["id"]
    unknown = str(uuid.uuid4())
    for who in ("tech_h1", "tech_h2", "dept_icu", "dept_none"):
        for device in ("icu", "h2", unknown):  # own hospital, other hospital, non-existent
            _err(rq["assess"](h[who], device), 403, "forbidden")
        for aid in (existing, h2_assessment, unknown):
            _err(rq["correct"](h[who], aid, notes="x"), 403, "forbidden")
    # the same ids for an engineer: existence and scope are checked (after the role) -> 404
    _err(rq["assess"](h["eng_h1"], "h2"), 404, message="Device not found.")
    _err(rq["assess"](h["eng_h1"], unknown), 404, message="Device not found.")
    _err(rq["correct"](h["eng_h1"], h2_assessment, notes="x"), 404, message="Risk assessment not found.")
    _err(rq["correct"](h["eng_h1"], unknown, notes="x"), 404)
    # nothing was written by the refused calls
    assert rq["sql"]("SELECT count(*) FROM risk_assessments WHERE organization_id = :o", o=rq["world"]["org"])[0][0] == 2


def test_department_users_get_403_on_every_read(client, rq):
    h, d = rq["h"], rq["d"]
    aid = rq["assess"](h["eng_h1"], "icu").json()["id"]
    for who in ("dept_icu", "dept_none"):
        for url in (f"{API}/risk-assessments", f"{API}/risk-assessments/{aid}", f"{API}/risk-assessments/{uuid.uuid4()}",
                    f"{API}/devices/{d['icu']['id']}/risk-assessments", f"{API}/devices/{uuid.uuid4()}/risk-assessments"):
            _err(client.get(url, headers=h[who]), 403, "forbidden")
    # ...but they keep the cached level in the full device view of their own department (unchanged B3 behaviour)
    assert client.get(f"{API}/devices/{d['icu']['id']}", headers=h["dept_icu"]).json()["current_risk_level"] == "medium"


def test_read_scope_per_role(client, rq):
    h, d = rq["h"], rq["d"]
    h1 = rq["assess"](h["eng_h1"], "icu", "high", assessed_at=T1).json()["id"]
    h2 = rq["assess"](h["eng_h2"], "h2", "low", assessed_at=T1).json()["id"]
    for who, visible, hidden in (("tech_h1", h1, h2), ("eng_h1", h1, h2), ("tech_h2", h2, h1), ("eng_h2", h2, h1)):
        assert client.get(f"{API}/risk-assessments/{visible}", headers=h[who]).status_code == 200, who
        _err(client.get(f"{API}/risk-assessments/{hidden}", headers=h[who]), 404)
        ids = [a["id"] for a in client.get(f"{API}/risk-assessments", headers=h[who]).json()["items"]]
        assert ids == [visible], who
    _err(client.get(f"{API}/devices/{d['h2']['id']}/risk-assessments", headers=h["tech_h1"]), 404, message="Device not found.")
    _err(client.get(f"{API}/devices/{d['icu']['id']}/risk-assessments", headers=h["eng_h2"]), 404)
    assert client.get(f"{API}/devices/{d['icu']['id']}/risk-assessments", headers=h["tech_h1"]).json()["total"] == 1
    admin_ids = {a["id"] for a in client.get(f"{API}/risk-assessments", headers=h["admin"]).json()["items"]}
    assert admin_ids == {h1, h2}


def test_engineers_and_admins_write_in_their_scope(client, rq):
    h = rq["h"]
    r = rq["assess"](h["eng_h1"], "icu", "high", notes="  Alarm fault  ")
    assert r.status_code == 201, r.text
    body = r.json()
    w = rq["world"]
    assert body["risk_level"] == "high" and body["notes"] == "Alarm fault"
    assert body["assessed_by"]["id"] != w["admin_id"] and body["assessed_by"]["role"] == "biomedical_engineer"
    assert body["device"]["device_code"] == "S-ICU" and body["device"]["current_risk_level"] == "high"
    assert body["hospital_id"] == w["h1"]
    assert rq["assess"](h["admin"], "h2", "low").status_code == 201
    assert rq["assess"](h["eng_h2"], "h2", "medium", assessed_at=T1).status_code == 201


# ---- devices.current_risk_level: the trigger decides, the API reports ----------------------------------
def test_cached_level_follows_the_latest_assessment(client, rq):
    h, d = rq["h"], rq["d"]
    assert rq["level"]("icu") is None
    first = rq["assess"](h["eng_h1"], "icu", "medium", assessed_at=T2).json()
    assert first["device"]["current_risk_level"] == "medium" == rq["level"]("icu")
    newer = rq["assess"](h["eng_h1"], "icu", "critical", assessed_at=T3).json()
    assert newer["device"]["current_risk_level"] == "critical" == rq["level"]("icu")
    older = rq["assess"](h["eng_h1"], "icu", "low", assessed_at=T1).json()  # backdated: never overrides
    assert older["device"]["current_risk_level"] == "critical" == rq["level"]("icu")
    # correction moving the newest assessment before the others -> the June one is now the latest
    moved = rq["correct"](h["eng_h1"], newer["id"], assessed_at="2026-01-15T10:00:00+00:00").json()
    assert moved["device"]["current_risk_level"] == "medium" == rq["level"]("icu")
    # correction moving the oldest one after all others -> it becomes the latest
    assert rq["correct"](h["admin"], older["id"], assessed_at="2026-10-01T10:00:00+00:00").json()["device"]["current_risk_level"] == "low"
    # correcting the level of the latest assessment changes the cache; of an older one does not
    assert rq["correct"](h["eng_h1"], older["id"], risk_level="high").json()["device"]["current_risk_level"] == "high"
    assert rq["correct"](h["eng_h1"], first["id"], risk_level="critical").json()["device"]["current_risk_level"] == "high"
    device = client.get(f"{API}/devices/{d['icu']['id']}", headers=h["admin"]).json()
    assert device["current_risk_level"] == "high" == rq["level"]("icu")


def test_device_api_still_refuses_writing_the_cached_level(client, rq):
    h, d = rq["h"], rq["d"]
    r = client.patch(f"{API}/devices/{d['icu']['id']}", headers=h["admin"], json={"current_risk_level": "low"})
    assert r.status_code == 422
    assert rq["level"]("icu") is None


# ---- dates (D6) and equal times (D7) ------------------------------------------------------------------
def test_assessment_dates(client, rq):
    h = rq["h"]
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    _err(rq["assess"](h["eng_h1"], "icu", assessed_at=future), 400, message="The assessment date cannot be in the future.")
    aid = rq["assess"](h["eng_h1"], "icu", assessed_at=T1).json()["id"]          # past: fine
    _err(rq["correct"](h["eng_h1"], aid, assessed_at=future), 400, message="The assessment date cannot be in the future.")
    naive = rq["assess"](h["eng_h1"], "icu", assessed_at="2026-02-01T08:00:00").json()   # no offset = UTC
    assert _same_instant(naive["assessed_at"], "2026-02-01T08:00:00+00:00")
    now = rq["assess"](h["eng_h1"], "icu").json()                                  # default: now
    assert abs(datetime.fromisoformat(now["assessed_at"]) - datetime.now(timezone.utc)) < timedelta(minutes=5)
    assert rq["level"]("icu") == "medium"


def test_equal_assessment_times_are_refused(client, rq):
    h = rq["h"]
    a = rq["assess"](h["eng_h1"], "icu", "high", assessed_at=T1).json()["id"]
    b = rq["assess"](h["eng_h1"], "icu", "low", assessed_at=T2).json()["id"]
    # the same instant written with another offset is still the same instant
    _err(rq["assess"](h["admin"], "icu", "critical", assessed_at="2026-03-01T12:00:00+02:00"), 409, "duplicate_assessment_time")
    _err(rq["correct"](h["eng_h1"], b, assessed_at=T1), 409, "duplicate_assessment_time")
    # the same time on ANOTHER device is fine; correcting other fields, or re-sending the own time, is fine
    assert rq["assess"](h["eng_h1"], "lab", "critical", assessed_at=T1).status_code == 201
    assert rq["correct"](h["eng_h1"], a, notes="checked", assessed_at=T1).status_code == 200
    assert rq["correct"](h["eng_h1"], a, risk_level="medium").status_code == 200
    rows = rq["sql"]("SELECT count(*) FROM risk_assessments WHERE device_id = :d", d=rq["d"]["icu"]["id"])[0][0]
    assert rows == 2 and rq["level"]("icu") == "low"


# ---- device and hospital states (D8, D9) ----------------------------------------------------------------
def test_archived_devices_are_read_only_but_readable(client, rq):
    h, d = rq["h"], rq["d"]
    _err(rq["assess"](h["admin"], "archived"), 400, message="Archived devices cannot receive new risk assessments.")
    aid = rq["assess"](h["eng_h1"], "lab", "high", assessed_at=T1).json()["id"]
    assert client.delete(f"{API}/devices/{d['lab']['id']}", headers=h["admin"]).status_code == 200
    _err(rq["correct"](h["eng_h1"], aid, risk_level="low"), 400,
         message="Risk assessments of archived devices cannot be corrected.")
    _err(rq["assess"](h["eng_h1"], "lab"), 400)
    got = client.get(f"{API}/risk-assessments/{aid}", headers=h["tech_h1"]).json()
    assert got["risk_level"] == "high" and got["device"]["is_archived"] is True
    hist = client.get(f"{API}/devices/{d['lab']['id']}/risk-assessments", headers=h["eng_h1"]).json()
    assert [a["id"] for a in hist["items"]] == [aid]


def test_inactive_hospitals_take_no_new_or_corrected_assessments(client, rq):
    h = rq["h"]
    aid = rq["assess"](h["admin"], "h2", "high", assessed_at=T1).json()["id"]
    rq["set_hospital_active"]("h2", False)
    _err(rq["assess"](h["admin"], "h2"), 400, message="Hospital is inactive; risk assessments cannot be added to it.")
    _err(rq["correct"](h["admin"], aid, risk_level="low"), 400,
         message="Hospital is inactive; its risk assessments cannot be changed.")
    assert client.get(f"{API}/risk-assessments/{aid}", headers=h["admin"]).json()["risk_level"] == "high"


def test_decommissioned_and_out_of_service_devices_can_be_assessed(client, rq):
    h = rq["h"]
    rq["set_status"]("icu", "decommissioned")
    rq["set_status"]("lab", "out_of_service")
    assert rq["assess"](h["eng_h1"], "icu", "critical").status_code == 201
    assert rq["assess"](h["eng_h1"], "lab", "high").status_code == 201


# ---- trusted fields (D4b) and validation ----------------------------------------------------------------
def test_ownership_fields_come_from_the_device_and_the_caller(client, rq):
    h, d, w = rq["h"], rq["d"], rq["world"]
    for extra in ({"organization_id": w["other"]}, {"hospital_id": w["h2"]}, {"assessed_by": w["admin_id"]},
                  {"id": str(uuid.uuid4())}, {"created_at": T1}, {"risk_level": "severe"}, {"notes": "   "},
                  {"notes": "x" * 4001}):
        body = {"device_id": d["icu"]["id"], "risk_level": "low", **extra}
        _err(client.post(f"{API}/risk-assessments", headers=h["eng_h1"], json=body), 422)
    _err(client.post(f"{API}/risk-assessments", headers=h["eng_h1"], json={"risk_level": "low"}), 422)  # device_id required
    aid = rq["assess"](h["eng_h1"], "icu", "low", assessed_at=T1, notes="first").json()["id"]
    row = rq["sql"]("SELECT organization_id::text, hospital_id::text, device_id::text, assessed_by::text "
                    "FROM risk_assessments WHERE id = :i", i=aid)[0]
    eng_id = client.get(f"{API}/auth/me", headers=h["eng_h1"]).json()["id"]
    assert tuple(row) == (w["org"], w["h1"], d["icu"]["id"], eng_id)

    for body in ({"device_id": d["icu"]["id"]}, {"device_id": d["lab"]["id"]}, {"organization_id": w["org"]},
                 {"hospital_id": w["h1"]}, {"assessed_by": w["admin_id"]}, {}, {"risk_level": None},
                 {"assessed_at": None}, {"notes": ""}):
        _err(rq["correct"](h["eng_h1"], aid, **body), 422)
    assert tuple(rq["sql"]("SELECT organization_id::text, hospital_id::text, device_id::text, assessed_by::text "
                           "FROM risk_assessments WHERE id = :i", i=aid)[0]) == tuple(row)
    # notes: null clears them
    assert rq["correct"](h["admin"], aid, notes=None).json()["notes"] is None


# ---- audit (same transaction) and D17 -------------------------------------------------------------------
def _audit(rq, record_id):
    return rq["sql"]("SELECT table_name, action::text, old_values, new_values, xmin::text, created_at "
                     "FROM audit_logs WHERE record_id = :r ORDER BY created_at, table_name", r=record_id)


def _level_audit(rq, device_id):
    """The D17 rows of a device: the level changes made by the trigger, each naming its cause (the
    device's other audit rows, e.g. its creation snapshot, are not D17 rows)."""
    return [r for r in _audit(rq, device_id) if r[3] and "cause" in r[3]]


def test_every_write_is_audited_with_the_device_level_change(client, rq):
    h, d = rq["h"], rq["d"]
    dev = d["icu"]["id"]
    aid = rq["assess"](h["eng_h1"], "icu", "high", assessed_at=T2).json()["id"]
    [ins] = _audit(rq, aid)
    assert ins[0:2] == ("risk_assessments", "insert") and ins[3]["risk_level"] == "high" and ins[3]["device_id"] == dev
    assert rq["sql"]("SELECT xmin::text FROM risk_assessments WHERE id = :i", i=aid)[0][0] == ins[4]
    [cache] = _level_audit(rq, dev)
    assert cache[0:2] == ("devices", "update") and cache[4] == ins[4]          # same transaction
    assert cache[2] == {"current_risk_level": None}
    assert cache[3] == {"current_risk_level": "high",
                        "cause": {"table": "risk_assessments", "record_id": aid, "action": "insert"}}
    assert cache[5] > ins[5]  # clock_timestamp(): sorts after the assessment's own row

    # a backdated assessment leaves the level unchanged -> its insert is audited, but no device row
    old = rq["assess"](h["eng_h1"], "icu", "low", assessed_at=T1).json()["id"]
    assert [r[0:2] for r in _audit(rq, old)] == [("risk_assessments", "insert")]
    assert len(_level_audit(rq, dev)) == 1

    # a correction that moves the latest changes the level: update row (changed fields only) + device row
    rq["correct"](h["admin"], old, assessed_at=T3)
    upd = _audit(rq, old)[-1]
    assert upd[0:2] == ("risk_assessments", "update") and set(upd[3]) == {"assessed_at"}
    cache2 = _level_audit(rq, dev)[-1]
    assert cache2[2] == {"current_risk_level": "high"} and cache2[3]["current_risk_level"] == "low"
    assert cache2[3]["cause"] == {"table": "risk_assessments", "record_id": old, "action": "update"}
    assert cache2[4] == upd[4]
    # a correction that changes nothing writes nothing
    before = rq["sql"]("SELECT count(*) FROM audit_logs WHERE record_id IN (:a, :b)", a=old, b=dev)[0][0]
    assert rq["correct"](h["admin"], old, risk_level="low").status_code == 200
    assert rq["sql"]("SELECT count(*) FROM audit_logs WHERE record_id IN (:a, :b)", a=old, b=dev)[0][0] == before


def test_a_refused_write_leaves_nothing_behind(client, rq):
    h = rq["h"]
    rq["assess"](h["eng_h1"], "icu", "high", assessed_at=T1)
    n = lambda: rq["sql"]("SELECT (SELECT count(*) FROM risk_assessments WHERE organization_id = :o), "  # noqa: E731
                          "(SELECT count(*) FROM audit_logs WHERE organization_id = :o)", o=rq["world"]["org"])[0]
    before = tuple(n())
    _err(rq["assess"](h["eng_h1"], "icu", "low", assessed_at=T1), 409)
    _err(rq["assess"](h["eng_h1"], "archived"), 400)
    assert tuple(n()) == before and rq["level"]("icu") == "high"


# ---- lists: filters, sorting, paging ---------------------------------------------------------------------
def test_lists_filter_sort_and_page(client, rq):
    h, d = rq["h"], rq["d"]
    ids = {}
    for key, device, level, at in (("a", "icu", "low", T1), ("b", "icu", "critical", T2), ("c", "lab", "medium", T3),
                                   ("e", "icu", "high", "2026-10-01T10:00:00+00:00")):
        ids[key] = rq["assess"](h["eng_h1"], device, level, assessed_at=at).json()["id"]
    get = lambda **q: client.get(f"{API}/risk-assessments", headers=h["tech_h1"], params=q).json()  # noqa: E731
    assert [a["id"] for a in get()["items"]] == [ids["e"], ids["c"], ids["b"], ids["a"]]       # newest first
    assert [a["id"] for a in get(order="asc")["items"]] == [ids["a"], ids["b"], ids["c"], ids["e"]]
    assert [a["risk_level"] for a in get(sort="risk_level")["items"]] == ["critical", "high", "medium", "low"]
    assert [a["id"] for a in get(device_id=d["icu"]["id"])["items"]] == [ids["e"], ids["b"], ids["a"]]
    assert [a["id"] for a in get(risk_level="critical")["items"]] == [ids["b"]]
    assert [a["id"] for a in get(assessed_from=T2, assessed_to=T3)["items"]] == [ids["b"]]          # [from, to)
    eng = client.get(f"{API}/auth/me", headers=h["eng_h1"]).json()["id"]
    assert get(assessed_by=eng)["total"] == 4 and get(assessed_by=str(uuid.uuid4()))["total"] == 0
    page = get(page=2, page_size=3)
    assert page["total"] == 4 and [a["id"] for a in page["items"]] == [ids["a"]]
    hist = client.get(f"{API}/devices/{d['icu']['id']}/risk-assessments", headers=h["tech_h1"]).json()
    assert [a["id"] for a in hist["items"]] == [ids["e"], ids["b"], ids["a"]] and hist["total"] == 3
    _err(client.get(f"{API}/risk-assessments", headers=h["tech_h1"], params={"sort": "notes"}), 422)
    _err(client.get(f"{API}/risk-assessments", headers=h["tech_h1"], params={"risk_level": "severe"}), 422)


def test_openapi_lists_no_delete_for_assessments(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert set(paths[f"{API}/risk-assessments"]) == {"get", "post"}
    assert set(paths[f"{API}/risk-assessments/{{assessment_id}}"]) == {"get", "patch"}
    assert set(paths[f"{API}/devices/{{device_id}}/risk-assessments"]) == {"get"}
