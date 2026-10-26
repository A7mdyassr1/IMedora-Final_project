"""
B3 flows against REAL PostgreSQL (device management, structure, catalog, QR).
Skipped unless TEST_DATABASE_URL is set. Everything created here is removed again.
"""
import uuid

import pytest
from sqlalchemy import delete, text

from app.core.database import get_session_factory
from app.models import Device, DeviceCategory, DeviceModel, Manufacturer
from tests.world import API, PW, auth, login


# ---- fixtures ---------------------------------------------------------------------------
@pytest.fixture
def cat(world):
    """Catalog rows (global tables, so every name carries this run's suffix) + cleanup of
    everything that references them or the world's organizations."""
    factory = get_session_factory()
    sfx = world["sfx"]
    with factory() as db:
        m1, m2 = Manufacturer(name=f"Acme-{sfx}"), Manufacturer(name=f"Globex-{sfx}")
        c1, c2 = DeviceCategory(name=f"Ventilator-{sfx}"), DeviceCategory(name=f"Monitor-{sfx}")
        db.add_all([m1, m2, c1, c2])
        db.flush()
        a = DeviceModel(manufacturer_id=m1.id, device_category_id=c1.id, name="Vent-A")
        b = DeviceModel(manufacturer_id=m2.id, device_category_id=c2.id, name="Mon-B")
        db.add_all([a, b])
        db.commit()
        data = dict(m1=str(m1.id), m2=str(m2.id), c1=str(c1.id), c2=str(c2.id), model_a=str(a.id), model_b=str(b.id))
    yield data
    with factory() as db:
        orgs = [world["org"], world["other"]]
        db.execute(text("DELETE FROM risk_assessments WHERE organization_id = ANY(CAST(:o AS uuid[]))"), {"o": orgs})
        db.execute(delete(Device).where(Device.organization_id.in_([uuid.UUID(o) for o in orgs])))
        db.execute(text("DELETE FROM device_models WHERE manufacturer_id IN (SELECT id FROM manufacturers WHERE name LIKE :p)"), {"p": f"%-{sfx}"})
        db.execute(text("DELETE FROM manufacturers WHERE name LIKE :p"), {"p": f"%-{sfx}"})
        db.execute(text("DELETE FROM device_categories WHERE name LIKE :p"), {"p": f"%-{sfx}"})
        db.commit()


@pytest.fixture
def eng(client, world):
    """An authenticated biomedical engineer (created by the admin through the API)."""
    admin = auth(client, world["admin"])
    email = f"eng-{world['sfx']}@b2.test"
    r = client.post(f"{API}/users", headers=admin, json=dict(
        email=email, full_name="Engineer", password=PW, role="biomedical_engineer", hospital_id=world["h1"]))
    assert r.status_code == 201, r.text
    return auth(client, email)


def device_body(world, cat, **over):
    return {**dict(hospital_id=world["h1"], department_id=world["icu"], device_model_id=cat["model_a"],
                   device_code=f"D-{uuid.uuid4().hex[:6]}", name="Ventilator 1"), **over}


def make_device(client, headers, world, cat, **over):
    r = client.post(f"{API}/devices", headers=headers, json=device_body(world, cat, **over))
    assert r.status_code == 201, r.text
    return r.json()


# ---- create / read / update -----------------------------------------------------------------
def test_engineer_registers_a_device(client, world, cat, eng):
    admin = auth(client, world["admin"])
    loc = client.post(f"{API}/locations", headers=admin, json=dict(hospital_id=world["h1"], building="Main", floor="2", room="204")).json()
    assert loc["label"] == "Main - 2 - 204"

    d = make_device(client, eng, world, cat, location_id=loc["id"], serial_number="SN-1",
                    criticality="critical", installation_date="2024-03-10", warranty_expiry="2027-03-10")
    assert d["status"] == "active" and d["criticality"] == "critical"
    assert d["qr_identifier"].startswith("IMD-")  # generated
    assert (d["hospital_name"], d["department_name"], d["location"]) == ("Hospital One", "ICU", "Main - 2 - 204")
    assert (d["manufacturer_name"], d["model_name"]) == (f"Acme-{world['sfx']}", "Vent-A")
    assert d["is_archived"] is False and d["current_risk_level"] is None
    assert client.get(f"{API}/devices/{d['id']}", headers=eng).json()["id"] == d["id"]


def test_update_device(client, world, cat, eng):
    d = make_device(client, eng, world, cat)
    r = client.patch(f"{API}/devices/{d['id']}", headers=eng, json=dict(name="Renamed", status="under_maintenance", device_model_id=cat["model_b"]))
    assert r.status_code == 200, r.text
    assert (r.json()["name"], r.json()["status"], r.json()["model_name"]) == ("Renamed", "under_maintenance", "Mon-B")
    assert r.json()["updated_at"] >= d["updated_at"]
    assert client.patch(f"{API}/devices/{d['id']}", headers=eng, json=dict(hospital_id=world["h2"])).status_code == 422


def test_database_rules_come_back_as_clear_errors(client, world, cat, eng):
    d = make_device(client, eng, world, cat, device_code="DUP-1")
    r = client.post(f"{API}/devices", headers=eng, json=device_body(world, cat, device_code="DUP-1"))
    assert r.status_code == 409 and "code already exists" in r.json()["error"]["message"]
    # same code in ANOTHER hospital is fine (unique per hospital)
    ok = client.post(f"{API}/devices", headers=eng, json=device_body(world, cat, device_code="DUP-1", hospital_id=world["h2"], department_id=world["rad"]))
    assert ok.status_code == 201
    r = client.post(f"{API}/devices", headers=eng, json=device_body(world, cat, qr_identifier=d["qr_identifier"]))
    assert r.status_code == 409 and "QR identifier" in r.json()["error"]["message"]
    r = client.post(f"{API}/devices", headers=eng, json=device_body(world, cat, installation_date="2026-01-01", warranty_expiry="2020-01-01"))
    assert r.status_code == 422 and r.json()["error"]["code"] == "constraint_violation"
    assert "Warranty expiry" in r.json()["error"]["message"]


def test_placement_must_stay_inside_the_organization_and_hospital(client, world, cat, eng):
    admin = auth(client, world["admin"])
    other_loc = client.post(f"{API}/locations", headers=admin, json=dict(hospital_id=world["h2"], room="9")).json()
    for over in (
        dict(hospital_id=world["oh"]),                 # another organization's hospital
        dict(department_id=world["rad"]),              # department of a different hospital
        dict(location_id=other_loc["id"]),             # location of a different hospital
        dict(device_model_id=str(uuid.uuid4())),       # unknown model
    ):
        assert client.post(f"{API}/devices", headers=eng, json=device_body(world, cat, **over)).status_code == 400, over


def test_read_only_staff_cannot_write(client, world, cat, eng):
    d = make_device(client, eng, world, cat)
    for who in ("tech", "staff"):
        h = auth(client, world[who])
        assert client.get(f"{API}/devices/{d['id']}", headers=h).status_code == 200
        assert client.post(f"{API}/devices", headers=h, json=device_body(world, cat)).status_code == 403
        assert client.patch(f"{API}/devices/{d['id']}", headers=h, json={"name": "x"}).status_code == 403
        assert client.delete(f"{API}/devices/{d['id']}", headers=h).status_code == 403


def test_other_organizations_are_invisible(client, world, cat, eng):
    d = make_device(client, eng, world, cat)
    stranger = login(client, f"stranger-{world['sfx']}@b2.test").json()["access_token"]
    h = {"Authorization": f"Bearer {stranger}"}
    assert client.get(f"{API}/devices/{d['id']}", headers=h).status_code == 404
    assert client.get(f"{API}/devices/qr/{d['qr_identifier']}", headers=h).status_code == 404
    assert client.get(f"{API}/devices", headers=h).json()["total"] == 0
    assert client.get(f"{API}/hospitals/{world['h1']}", headers=h).status_code == 404


# ---- list / search / filter / sort -------------------------------------------------------------
def test_list_filters_search_sort_and_pagination(client, world, cat, eng):
    a = make_device(client, eng, world, cat, name="Alpha Vent", device_code="A-1", serial_number="SERIAL-AAA", criticality="critical")
    b = make_device(client, eng, world, cat, name="Bravo Monitor", device_code="B-1", device_model_id=cat["model_b"],
                    department_id=world["icu"], status="out_of_service", criticality="low")
    c = make_device(client, eng, world, cat, name="Charlie Vent", device_code="C-1", hospital_id=world["h2"], department_id=world["rad"])

    def ids(**params):
        r = client.get(f"{API}/devices", headers=eng, params=params)
        assert r.status_code == 200, r.text
        return {i["id"] for i in r.json()["items"]}

    assert ids() == {a["id"], b["id"], c["id"]}
    assert ids(hospital_id=world["h2"]) == {c["id"]}
    assert ids(department_id=world["icu"]) == {a["id"], b["id"]}
    assert ids(category_id=cat["c2"]) == {b["id"]}
    assert ids(manufacturer_id=cat["m1"]) == {a["id"], c["id"]}
    assert ids(model_id=cat["model_b"]) == {b["id"]}
    assert ids(status="out_of_service") == {b["id"]}
    assert ids(criticality="critical") == {a["id"]}
    assert ids(q="bravo") == {b["id"]}
    assert ids(q="serial-aaa") == {a["id"]}
    assert ids(q=c["qr_identifier"][:10].lower()) >= {c["id"]}

    page = client.get(f"{API}/devices", headers=eng, params={"sort": "name", "order": "desc", "page_size": 2}).json()
    assert [i["name"] for i in page["items"]] == ["Charlie Vent", "Bravo Monitor"] and page["total"] == 3
    page2 = client.get(f"{API}/devices", headers=eng, params={"sort": "name", "order": "desc", "page_size": 2, "page": 2}).json()
    assert [i["name"] for i in page2["items"]] == ["Alpha Vent"]
    assert client.get(f"{API}/devices", headers=eng, params={"sort": "password"}).status_code == 422
    assert client.get(f"{API}/devices", headers=eng, params={"status": "exploded"}).status_code == 422


def test_risk_level_is_trigger_maintained_and_filterable(client, world, cat, eng):
    d = make_device(client, eng, world, cat)
    other = make_device(client, eng, world, cat)
    with get_session_factory()() as db:  # risk assessments belong to B6; insert directly, PostgreSQL's trigger updates the cache
        db.execute(text(
            "INSERT INTO risk_assessments (organization_id, hospital_id, device_id, assessed_by, risk_level) "
            "VALUES (:o, :h, :d, :u, 'high')"), dict(o=world["org"], h=world["h1"], d=d["id"], u=world["admin_id"]))
        db.commit()
    got = client.get(f"{API}/devices/{d['id']}", headers=eng).json()
    assert got["current_risk_level"] == "high"
    items = client.get(f"{API}/devices", headers=eng, params={"risk_level": "high"}).json()["items"]
    assert [i["id"] for i in items] == [d["id"]] and other["id"] not in [i["id"] for i in items]
    # read-only: the API never accepts it
    assert client.patch(f"{API}/devices/{d['id']}", headers=eng, json={"current_risk_level": "low"}).status_code == 422


# ---- QR -----------------------------------------------------------------------------------------
def test_qr_lookup(client, world, cat, eng):
    d = make_device(client, eng, world, cat, qr_identifier=f"QR-{world['sfx']}-ABC")
    staff = auth(client, world["staff"])  # the mobile app's user: a plain department_user
    r = client.get(f"{API}/devices/qr/{d['qr_identifier']}", headers=staff)
    assert r.status_code == 200 and r.json()["id"] == d["id"]
    assert client.get(f"{API}/devices/qr/{d['qr_identifier'].lower()}", headers=staff).json()["id"] == d["id"]
    r = client.get(f"{API}/devices/qr/NOPE-123", headers=staff)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


# ---- archive --------------------------------------------------------------------------------------
def test_archive_is_a_soft_delete(client, world, cat, eng):
    d = make_device(client, eng, world, cat)
    r = client.delete(f"{API}/devices/{d['id']}", headers=eng)
    assert r.status_code == 200 and r.json()["is_archived"] is True and r.json()["status"] == "decommissioned"
    assert client.delete(f"{API}/devices/{d['id']}", headers=eng).status_code == 200  # idempotent
    assert d["id"] not in {i["id"] for i in client.get(f"{API}/devices", headers=eng).json()["items"]}
    shown = client.get(f"{API}/devices", headers=eng, params={"include_archived": True}).json()["items"]
    assert d["id"] in {i["id"] for i in shown}
    assert client.get(f"{API}/devices/{d['id']}", headers=eng).json()["is_archived"] is True   # history can still resolve it
    assert client.get(f"{API}/devices/qr/{d['qr_identifier']}", headers=eng).status_code == 200
    assert client.patch(f"{API}/devices/{d['id']}", headers=eng, json={"name": "x"}).status_code == 400


# ---- structure ---------------------------------------------------------------------------------------
def test_location_delete_detaches_devices_instead_of_deleting_them(client, world, cat, eng):
    admin = auth(client, world["admin"])
    loc = client.post(f"{API}/locations", headers=admin, json=dict(hospital_id=world["h1"], room="Temp")).json()
    d = make_device(client, eng, world, cat, location_id=loc["id"])
    assert client.delete(f"{API}/locations/{loc['id']}", headers=admin).status_code == 204
    after = client.get(f"{API}/devices/{d['id']}", headers=eng).json()
    assert after["location_id"] is None and after["location"] is None


def test_department_with_devices_cannot_be_deleted(client, world, cat, eng):
    admin = auth(client, world["admin"])
    make_device(client, eng, world, cat)  # uses ICU
    r = client.delete(f"{API}/departments/{world['icu']}", headers=admin)
    assert r.status_code == 409 and "still has devices" in r.json()["error"]["message"]
    empty = client.post(f"{API}/departments", headers=admin, json=dict(hospital_id=world["h1"], name="Empty Dept")).json()
    assert client.delete(f"{API}/departments/{empty['id']}", headers=admin).status_code == 204
    dup = client.post(f"{API}/departments", headers=admin, json=dict(hospital_id=world["h1"], name="ICU"))
    assert dup.status_code == 409 and "already exists in this hospital" in dup.json()["error"]["message"]
    assert client.post(f"{API}/departments", headers=admin, json=dict(hospital_id=world["oh"], name="X")).status_code == 400


def test_hospital_management(client, world):
    admin = auth(client, world["admin"])
    r = client.post(f"{API}/hospitals", headers=admin, json=dict(name="Third Hospital", code="H3", address="Cairo"))
    assert r.status_code == 201 and r.json()["is_active"] is True
    hid = r.json()["id"]
    assert client.post(f"{API}/hospitals", headers=admin, json=dict(name="Again", code="H3")).status_code == 409
    assert client.patch(f"{API}/hospitals/{hid}", headers=admin, json={"is_active": False}).json()["is_active"] is False
    active = client.get(f"{API}/hospitals", headers=admin, params={"is_active": True}).json()
    assert hid not in {h["id"] for h in active["items"]} and active["total"] == 2
    assert client.get(f"{API}/hospitals", headers=admin, params={"q": "third"}).json()["total"] == 1
    assert client.get(f"{API}/hospitals/{world['oh']}", headers=admin).status_code == 404  # other organization's


def test_organization_current(client, world):
    admin = auth(client, world["admin"])
    assert client.get(f"{API}/organizations/current", headers=admin).json()["id"] == world["org"]
    assert client.patch(f"{API}/organizations/current", headers=admin, json={"name": "Renamed Org"}).json()["name"] == "Renamed Org"
    assert client.patch(f"{API}/organizations/current", headers=auth(client, world["tech"]), json={"name": "x"}).status_code == 403


# ---- catalog ---------------------------------------------------------------------------------------------
def test_catalog_management(client, world, cat, eng):
    sfx = world["sfx"]
    m = client.post(f"{API}/manufacturers", headers=eng, json={"name": f"  Initech-{sfx} "}).json()
    assert m["name"] == f"Initech-{sfx}"  # trimmed
    assert client.post(f"{API}/manufacturers", headers=eng, json={"name": f"Initech-{sfx}"}).status_code == 409
    c = client.post(f"{API}/device-categories", headers=eng, json={"name": f"Pump-{sfx}"}).json()
    model = client.post(f"{API}/device-models", headers=eng, json=dict(manufacturer_id=m["id"], device_category_id=c["id"], name="P-1"))
    assert model.status_code == 201 and model.json()["manufacturer_name"] == m["name"] and model.json()["category_name"] == c["name"]
    assert client.post(f"{API}/device-models", headers=eng, json=dict(manufacturer_id=m["id"], device_category_id=c["id"], name="P-1")).status_code == 409
    assert client.post(f"{API}/device-models", headers=eng, json=dict(manufacturer_id=str(uuid.uuid4()), device_category_id=c["id"], name="Z")).status_code == 400

    staff = auth(client, world["staff"])  # everyone can read the catalog
    only = client.get(f"{API}/device-models", headers=staff, params={"manufacturer_id": m["id"]}).json()
    assert only["total"] == 1 and only["items"][0]["name"] == "P-1"
    assert client.get(f"{API}/manufacturers", headers=staff, params={"q": f"initech-{sfx}"}).json()["total"] == 1

    # deleting something still in use is refused with an explanation
    r = client.delete(f"{API}/device-models/{cat['model_a']}", headers=eng)
    assert r.status_code == 204  # nothing uses it yet
    make_device(client, eng, world, cat, device_model_id=cat["model_b"])
    r = client.delete(f"{API}/device-models/{cat['model_b']}", headers=eng)
    assert r.status_code == 409 and "used by devices" in r.json()["error"]["message"]
    r = client.delete(f"{API}/manufacturers/{cat['m2']}", headers=eng)
    assert r.status_code == 409 and "still has device models" in r.json()["error"]["message"]
