"""B6 CP2 - QA records against REAL PostgreSQL: permissions in the approved order, status rules (D5),
corrections of finalized records, the next-due-date rule (pre-check and the CHECK constraint, both
422), dates (D6), device and hospital states (D8, D9), trusted fields (D4b), no side effects (D11),
audit in the same transaction, filters, sorting and paging.
Skipped unless TEST_DATABASE_URL is set; everything created here is removed (tests/risk_scene.py).
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import get_settings
from app.core.database import get_db
from app.services.qa_service import QAService
from tests.risk_scene import rq  # noqa: F401
from tests.scope_scene import scene  # noqa: F401
from tests.test_devices_flow import cat  # noqa: F401
from tests.ticket_scene import tickets  # noqa: F401
from tests.world import API

T1, T2, T3 = "2026-03-01T10:00:00+00:00", "2026-06-01T10:00:00+00:00", "2026-09-01T10:00:00+00:00"
DUE_MESSAGE = "The next due date cannot be before the date the QA check was performed."


def _err(r, status, code=None, message=None):
    assert r.status_code == status, r.text
    if code:
        assert r.json()["error"]["code"] == code, r.text
    if message:
        assert r.json()["error"]["message"] == message, r.text
    return r.json()["error"]


# ---- permissions, in the approved order -------------------------------------------------------------
def test_unauthorized_roles_get_403_before_any_lookup(client, rq):
    h = rq["h"]
    own = rq["qa"](h["eng_h1"], "icu").json()["id"]
    other = rq["qa"](h["admin"], "h2").json()["id"]
    unknown = str(uuid.uuid4())
    for who in ("tech_h1", "tech_h2", "dept_icu", "dept_none"):
        for device in ("icu", "h2", unknown):
            _err(rq["qa"](h[who], device), 403, "forbidden")
        for rid in (own, other, unknown):
            _err(rq["qa_update"](h[who], rid, status="pass"), 403, "forbidden")
    _err(rq["qa"](h["eng_h1"], "h2"), 404, message="Device not found.")
    _err(rq["qa"](h["eng_h1"], unknown), 404, message="Device not found.")
    _err(rq["qa_update"](h["eng_h1"], other, status="pass"), 404, message="QA record not found.")
    _err(rq["qa_update"](h["eng_h1"], unknown, status="pass"), 404)
    assert rq["sql"]("SELECT array_agg(status::text) FROM qa_records WHERE organization_id = :o",
                     o=rq["world"]["org"])[0][0] == ["pending", "pending"]


def test_read_access_per_role(client, rq):
    h, d = rq["h"], rq["d"]
    own = rq["qa"](h["eng_h1"], "icu").json()["id"]
    other = rq["qa"](h["eng_h2"], "h2").json()["id"]
    for who in ("dept_icu", "dept_none"):
        for url in (f"{API}/qa-records", f"{API}/qa-records/{own}", f"{API}/qa-records/{uuid.uuid4()}",
                    f"{API}/devices/{d['icu']['id']}/qa-records"):
            _err(client.get(url, headers=h[who]), 403, "forbidden")
    for who, visible, hidden in (("tech_h1", own, other), ("tech_h2", other, own), ("eng_h2", other, own)):
        assert client.get(f"{API}/qa-records/{visible}", headers=h[who]).status_code == 200
        _err(client.get(f"{API}/qa-records/{hidden}", headers=h[who]), 404)
        assert [r["id"] for r in client.get(f"{API}/qa-records", headers=h[who]).json()["items"]] == [visible]
    _err(client.get(f"{API}/devices/{d['h2']['id']}/qa-records", headers=h["tech_h1"]), 404)
    assert {r["id"] for r in client.get(f"{API}/qa-records", headers=h["admin"]).json()["items"]} == {own, other}


def test_create_sets_trusted_fields_and_defaults(client, rq):
    h, d, w = rq["h"], rq["d"], rq["world"]
    r = rq["qa"](h["eng_h1"], "icu", "inspection", findings="  No issues found  ", next_due_date="2027-01-10")
    assert r.status_code == 201, r.text
    body = r.json()
    eng = client.get(f"{API}/auth/me", headers=h["eng_h1"]).json()["id"]
    assert body["status"] == "pending" and body["findings"] == "No issues found" and body["record_type"] == "inspection"
    assert body["performed_by"]["id"] == eng and body["hospital_id"] == w["h1"] and body["next_due_date"] == "2027-01-10"
    assert abs(datetime.fromisoformat(body["performed_at"]) - datetime.now(timezone.utc)) < timedelta(minutes=5)
    row = rq["sql"]("SELECT organization_id::text, hospital_id::text, device_id::text, performed_by::text "
                    "FROM qa_records WHERE id = :i", i=body["id"])[0]
    assert tuple(row) == (w["org"], w["h1"], d["icu"]["id"], eng)
    for record_type in ("calibration", "compliance"):
        assert rq["qa"](h["admin"], "h2", record_type, performed_at=T1).status_code == 201
    # a completed check can be recorded directly with its (final) result
    assert rq["qa"](h["eng_h1"], "icu", status="pass", performed_at=T1).json()["status"] == "pass"
    assert rq["qa"](h["eng_h1"], "icu", status="fail", performed_at=T1).json()["status"] == "fail"


# ---- status (D5) ------------------------------------------------------------------------------------
def test_status_transitions(client, rq):
    h = rq["h"]
    a = rq["qa"](h["eng_h1"], "icu").json()["id"]
    b = rq["qa"](h["eng_h1"], "icu").json()["id"]
    assert rq["qa_update"](h["eng_h1"], a, status="pass").json()["status"] == "pass"
    assert rq["qa_update"](h["admin"], b, status="fail").json()["status"] == "fail"
    for rid, current, target in ((a, "pass", "fail"), (a, "pass", "pending"), (b, "fail", "pass"), (b, "fail", "pending")):
        err = _err(rq["qa_update"](h["admin"], rid, status=target), 409, "invalid_qa_status_transition")
        assert err["details"] == [{"from": current, "to": target, "allowed": []}]
        assert rq["sql"]("SELECT status::text FROM qa_records WHERE id = :i", i=rid)[0][0] == current
    # sending the current status again is not a transition
    assert rq["qa_update"](h["eng_h1"], a, status="pass").status_code == 200
    c = rq["qa"](h["eng_h1"], "icu").json()["id"]
    assert rq["qa_update"](h["eng_h1"], c, status="pending").json()["status"] == "pending"


def test_finalized_records_can_still_be_corrected(client, rq):
    h = rq["h"]
    rid = rq["qa"](h["eng_h1"], "icu", status="fail", performed_at=T1, findings="Battery test failed").json()["id"]
    r = rq["qa_update"](h["admin"], rid, findings="Battery self-test failed at 40%", next_due_date="2026-04-01")
    assert r.status_code == 200 and r.json()["findings"] == "Battery self-test failed at 40%"
    r = rq["qa_update"](h["eng_h1"], rid, status="fail", performed_at=T2, next_due_date="2026-07-01")
    assert r.status_code == 200 and r.json()["status"] == "fail"
    assert datetime.fromisoformat(r.json()["performed_at"]) == datetime.fromisoformat(T2)
    cleared = rq["qa_update"](h["eng_h1"], rid, findings=None, next_due_date=None).json()
    assert cleared["findings"] is None and cleared["next_due_date"] is None
    updates = rq["sql"]("SELECT new_values FROM audit_logs WHERE record_id = :i AND action = 'update' "
                        "ORDER BY created_at", i=rid)
    assert [set(u[0]) for u in updates] == [{"findings", "next_due_date"}, {"performed_at", "next_due_date"},
                                           {"findings", "next_due_date"}]


# ---- the next-due-date rule (422 either way) ------------------------------------------------------------
def test_next_due_date_follows_the_database_date_of_the_check(client, rq):
    h = rq["h"]
    near_midnight = "2026-03-01T23:30:00+00:00"   # in a time zone east of UTC this is already 2 March
    db_date = rq["sql"]("SELECT CAST(CAST(:t AS timestamptz) AS date)", t=near_midnight)[0][0]
    day_before = str(db_date - timedelta(days=1))
    _err(rq["qa"](h["eng_h1"], "icu", performed_at=near_midnight, next_due_date=day_before), 422,
         "constraint_violation", DUE_MESSAGE)
    rid = rq["qa"](h["eng_h1"], "icu", performed_at=near_midnight, next_due_date=str(db_date)).json()["id"]  # same day: fine
    # corrections: moving the check after its due date, or the due date before the check
    _err(rq["qa_update"](h["eng_h1"], rid, performed_at=T2), 422, "constraint_violation", DUE_MESSAGE)
    _err(rq["qa_update"](h["eng_h1"], rid, next_due_date=day_before), 422, "constraint_violation", DUE_MESSAGE)
    assert rq["qa_update"](h["eng_h1"], rid, performed_at=T2, next_due_date="2026-12-01").status_code == 200


WEST_OF_UTC = "America/New_York"


@pytest.fixture
def west_db(client):
    """B6-L1: every request's database session runs with a time zone WEST of UTC.

    East of UTC (the default test database, Africa/Cairo) a check computed in UTC is looser than the
    database's own date, so the CHECK constraint still answers the same 422 and a UTC-based service
    check would go unnoticed. West of UTC the UTC date is AHEAD of the database date: a UTC-based check
    would refuse a due date the database accepts. Yields a session factory with the same setting."""
    engine = create_engine(get_settings().database_url.get_secret_value(), poolclass=NullPool,
                           connect_args={"options": f"-c TimeZone={WEST_OF_UTC}"})
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def west_session():
        db = factory()
        try:
            yield db
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    client.app.dependency_overrides[get_db] = west_session
    try:
        yield factory
    finally:
        client.app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_next_due_date_follows_the_database_date_west_of_utc(client, rq, west_db):
    """B6-L1 regression: 02:30 UTC on 2 March is still 1 March in New York. The rule compares with the
    DATABASE's date of performed_at (1 March), never with the UTC date (2 March)."""
    h = rq["h"]
    after_utc_midnight = "2026-03-02T02:30:00+00:00"
    with west_db() as s:
        zone, db_date = s.execute(text("SELECT current_setting('TimeZone'), CAST(CAST(:t AS timestamptz) AS date)"),
                                  {"t": after_utc_midnight}).one()
    assert (zone, db_date) == (WEST_OF_UTC, date(2026, 3, 1))

    # create: the database's date is accepted (a UTC-based check would answer 422 here) ...
    r = rq["qa"](h["eng_h1"], "icu", performed_at=after_utc_midnight, next_due_date="2026-03-01")
    assert r.status_code == 201, r.text
    assert r.json()["next_due_date"] == "2026-03-01"
    # ... and the day before it is still refused, with the usual 422
    _err(rq["qa"](h["eng_h1"], "icu", performed_at=after_utc_midnight, next_due_date="2026-02-28"), 422,
         "constraint_violation", DUE_MESSAGE)

    # corrections follow the same date
    rid = rq["qa"](h["eng_h1"], "icu", performed_at=T1, next_due_date="2026-04-01").json()["id"]
    r = rq["qa_update"](h["eng_h1"], rid, performed_at=after_utc_midnight, next_due_date="2026-03-01")
    assert r.status_code == 200, r.text
    _err(rq["qa_update"](h["eng_h1"], rid, next_due_date="2026-02-28"), 422, "constraint_violation", DUE_MESSAGE)
    stored = rq["sql"]("SELECT performed_at, next_due_date FROM qa_records WHERE id = :i", i=rid)[0]
    assert stored == (datetime(2026, 3, 2, 2, 30, tzinfo=timezone.utc), date(2026, 3, 1))


def test_the_check_constraint_itself_also_gives_422(client, rq, monkeypatch):
    """With the service's pre-check switched off, the database CHECK still refuses the row and the
    existing error mapping turns it into the same 422 - never a raw error or a 500."""
    h = rq["h"]
    monkeypatch.setattr(QAService, "_check_due_date", lambda self, performed_at, next_due: None)
    _err(rq["qa"](h["eng_h1"], "icu", performed_at=T2, next_due_date="2026-01-01"), 422, "constraint_violation", DUE_MESSAGE)
    rid = rq["qa"](h["eng_h1"], "icu", performed_at=T1, next_due_date="2026-04-01").json()["id"]
    _err(rq["qa_update"](h["eng_h1"], rid, next_due_date="2026-01-01"), 422, "constraint_violation", DUE_MESSAGE)
    assert rq["sql"]("SELECT next_due_date FROM qa_records WHERE id = :i", i=rid)[0][0] == date(2026, 4, 1)


# ---- dates, states, trusted fields --------------------------------------------------------------------
def test_check_dates_cannot_be_in_the_future(client, rq):
    h = rq["h"]
    future = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    _err(rq["qa"](h["eng_h1"], "icu", performed_at=future), 400, message="The QA check date cannot be in the future.")
    rid = rq["qa"](h["eng_h1"], "icu", performed_at=T1).json()["id"]
    _err(rq["qa_update"](h["eng_h1"], rid, performed_at=future), 400)


def test_archived_devices_and_inactive_hospitals(client, rq):
    h, d = rq["h"], rq["d"]
    _err(rq["qa"](h["admin"], "archived"), 400, message="Archived devices cannot receive new QA records.")
    rid = rq["qa"](h["eng_h1"], "lab").json()["id"]
    assert client.delete(f"{API}/devices/{d['lab']['id']}", headers=h["admin"]).status_code == 200
    _err(rq["qa_update"](h["eng_h1"], rid, status="pass"), 400, message="QA records of archived devices cannot be changed.")
    assert client.get(f"{API}/qa-records/{rid}", headers=h["tech_h1"]).json()["device"]["is_archived"] is True
    assert client.get(f"{API}/devices/{d['lab']['id']}/qa-records", headers=h["tech_h1"]).json()["total"] == 1

    h2_record = rq["qa"](h["admin"], "h2").json()["id"]
    rq["set_hospital_active"]("h2", False)
    _err(rq["qa"](h["admin"], "h2"), 400, message="Hospital is inactive; QA records cannot be added to it.")
    _err(rq["qa_update"](h["admin"], h2_record, status="pass"), 400, message="Hospital is inactive; its QA records cannot be changed.")
    assert client.get(f"{API}/qa-records/{h2_record}", headers=h["admin"]).json()["status"] == "pending"


def test_decommissioned_and_out_of_service_devices_can_be_checked(client, rq):
    h = rq["h"]
    rq["set_status"]("icu", "decommissioned")
    rq["set_status"]("lab", "out_of_service")
    assert rq["qa"](h["eng_h1"], "icu", "compliance").status_code == 201
    assert rq["qa"](h["eng_h1"], "lab", "inspection").status_code == 201


def test_ownership_and_identity_fields_cannot_be_sent(client, rq):
    h, d, w = rq["h"], rq["d"], rq["world"]
    for extra in ({"organization_id": w["other"]}, {"hospital_id": w["h2"]}, {"performed_by": w["admin_id"]},
                  {"id": str(uuid.uuid4())}, {"created_at": T1}, {"record_type": "audit"}, {"status": "done"},
                  {"status": None}, {"findings": "  "}, {"findings": "x" * 4001}):
        body = {"device_id": d["icu"]["id"], "record_type": "calibration", **extra}
        _err(client.post(f"{API}/qa-records", headers=h["eng_h1"], json=body), 422)
    _err(client.post(f"{API}/qa-records", headers=h["eng_h1"], json={"record_type": "calibration"}), 422)
    rid = rq["qa"](h["eng_h1"], "icu", performed_at=T1).json()["id"]
    snapshot = lambda: tuple(rq["sql"]("SELECT organization_id, hospital_id, device_id, performed_by, record_type::text, "  # noqa: E731
                                       "status::text FROM qa_records WHERE id = :i", i=rid)[0])
    before = snapshot()
    for body in ({"device_id": d["icu"]["id"]}, {"device_id": d["lab"]["id"]}, {"record_type": "inspection"},
                 {"organization_id": w["org"]}, {"hospital_id": w["h1"]}, {"performed_by": w["admin_id"]}, {},
                 {"status": None}, {"performed_at": None}, {"findings": ""}):
        _err(rq["qa_update"](h["eng_h1"], rid, **body), 422)
    assert snapshot() == before


# ---- no side effects (D11) and audit ------------------------------------------------------------------
def test_a_failed_check_has_no_side_effects(client, rq):
    h, d = rq["h"], rq["d"]
    org = rq["world"]["org"]
    count = lambda: rq["sql"]("SELECT (SELECT count(*) FROM maintenance_tickets WHERE organization_id = :o), "  # noqa: E731
                              "(SELECT count(*) FROM notifications n JOIN users u ON u.id = n.user_id WHERE u.organization_id = :o)",
                              o=org)[0]
    status_before = client.get(f"{API}/devices/{d['icu']['id']}", headers=h["admin"]).json()["status"]
    before = tuple(count())
    rid = rq["qa"](h["eng_h1"], "icu", status="fail", findings="Leak current above limit").json()["id"]
    pending = rq["qa"](h["eng_h1"], "icu").json()["id"]
    assert rq["qa_update"](h["eng_h1"], pending, status="fail").status_code == 200
    assert tuple(count()) == before
    device = client.get(f"{API}/devices/{d['icu']['id']}", headers=h["admin"]).json()
    assert device["status"] == status_before and device["current_risk_level"] is None
    assert rid


def test_every_write_is_audited_in_the_same_transaction(client, rq):
    h, d = rq["h"], rq["d"]
    rid = rq["qa"](h["eng_h1"], "icu", "calibration", performed_at=T1, next_due_date="2026-09-01").json()["id"]
    rows = rq["sql"]("SELECT action::text, new_values, xmin::text FROM audit_logs WHERE record_id = :i ORDER BY created_at", i=rid)
    assert [r[0] for r in rows] == ["insert"] and rows[0][1]["status"] == "pending" and rows[0][1]["record_type"] == "calibration"
    assert rows[0][2] == rq["sql"]("SELECT xmin::text FROM qa_records WHERE id = :i", i=rid)[0][0]
    rq["qa_update"](h["eng_h1"], rid, status="pass", findings="Within tolerance")
    rows = rq["sql"]("SELECT action::text, old_values, new_values, xmin::text FROM audit_logs WHERE record_id = :i "
                     "ORDER BY created_at", i=rid)
    assert rows[-1][0] == "update" and rows[-1][1] == {"status": "pending", "findings": None}
    assert rows[-1][2] == {"status": "pass", "findings": "Within tolerance"}
    assert rows[-1][3] == rq["sql"]("SELECT xmin::text FROM qa_records WHERE id = :i", i=rid)[0][0]
    # an update that changes nothing writes nothing; QA never writes a device audit row
    assert rq["qa_update"](h["eng_h1"], rid, status="pass").status_code == 200
    assert len(rq["sql"]("SELECT 1 FROM audit_logs WHERE record_id = :i", i=rid)) == 2
    assert rq["sql"]("SELECT count(*) FROM audit_logs WHERE record_id = :d AND new_values ? 'cause'",
                     d=d["icu"]["id"])[0][0] == 0


# ---- lists ------------------------------------------------------------------------------------------
def test_lists_filter_sort_and_page(client, rq):
    h, d = rq["h"], rq["d"]
    ids = {}
    for key, device, record_type, status, at, due in (
            ("a", "icu", "calibration", "pass", T1, "2026-09-01"), ("b", "icu", "inspection", "fail", T2, None),
            ("c", "lab", "compliance", "pending", T3, "2027-03-01"), ("e", "icu", "calibration", "pending", T3, "2026-12-01")):
        r = rq["qa"](h["eng_h1"], device, record_type, status=status, performed_at=at, next_due_date=due)
        assert r.status_code == 201, r.text
        ids[key] = r.json()["id"]
    get = lambda **q: client.get(f"{API}/qa-records", headers=h["tech_h1"], params=q).json()  # noqa: E731
    order = [r["id"] for r in get()["items"]]
    assert order[2:] == [ids["b"], ids["a"]] and set(order[:2]) == {ids["c"], ids["e"]}     # newest first
    assert [r["id"] for r in get(sort="next_due_date", order="asc")["items"]] == [ids["a"], ids["e"], ids["c"], ids["b"]]
    assert [r["id"] for r in get(sort="next_due_date")["items"]] == [ids["c"], ids["e"], ids["a"], ids["b"]]  # NULL last
    assert {r["id"] for r in get(record_type="calibration")["items"]} == {ids["a"], ids["e"]}
    assert [r["id"] for r in get(status="fail")["items"]] == [ids["b"]]
    assert {r["id"] for r in get(device_id=d["icu"]["id"])["items"]} == {ids["a"], ids["b"], ids["e"]}
    assert [r["id"] for r in get(performed_from=T1, performed_to=T2)["items"]] == [ids["a"]]
    assert {r["id"] for r in get(due_after="2026-10-01")["items"]} == {ids["c"], ids["e"]}
    assert [r["id"] for r in get(due_before="2026-09-01")["items"]] == [ids["a"]]
    page = get(page=2, page_size=3)
    assert page["total"] == 4 and len(page["items"]) == 1
    dev = client.get(f"{API}/devices/{d['icu']['id']}/qa-records", headers=h["tech_h1"], params={"record_type": "calibration"}).json()
    assert [r["id"] for r in dev["items"]] == [ids["e"], ids["a"]]
    _err(client.get(f"{API}/qa-records", headers=h["tech_h1"], params={"status": "done"}), 422)


def test_openapi_lists_no_delete_for_qa_records(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert set(paths[f"{API}/qa-records"]) == {"get", "post"}
    assert set(paths[f"{API}/qa-records/{{record_id}}"]) == {"get", "patch"}
    assert set(paths[f"{API}/devices/{{device_id}}/qa-records"]) == {"get"}
