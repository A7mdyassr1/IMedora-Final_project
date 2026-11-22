"""
Role-based data scope against REAL PostgreSQL (B3.1 CP3). Skipped unless TEST_DATABASE_URL is set.

The approved matrix (H1 has ICU and Lab, H2 has Radiology):
    admin           -> whole organization
    engineer/tech   -> own hospital
    department user -> own department (QR: own hospital, limited view outside own department)
    no department   -> 403 department_required for every device read
Out-of-scope records are 404 (never 403), exactly like records that do not exist.
"""
import pytest

from tests.scope_scene import scene  # noqa: F401  (pytest fixture)
from tests.test_devices_flow import cat  # noqa: F401  (pytest fixture)
from tests.world import API

DEPARTMENT_REQUIRED = "An administrator must assign you to a department before you can access devices."


def listed(client, headers, **params):
    r = client.get(f"{API}/devices", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return {i["device_code"] for i in r.json()["items"]}, r.json()["total"]


# ---- T2: list ----------------------------------------------------------------------------------
def test_device_list_follows_the_scope_of_each_role(client, scene):
    h = scene["h"]
    assert listed(client, h["admin"]) == ({"S-ICU", "S-LAB", "S-H2"}, 3)
    for who in ("tech_h1", "eng_h1"):
        assert listed(client, h[who]) == ({"S-ICU", "S-LAB"}, 2), who
    for who in ("tech_h2", "eng_h2"):
        assert listed(client, h[who]) == ({"S-H2"}, 1), who
    assert listed(client, h["dept_icu"]) == ({"S-ICU"}, 1)


def test_query_parameters_cannot_widen_the_scope(client, scene):
    h, w = scene["h"], scene["world"]
    assert listed(client, h["tech_h1"], hospital_id=w["h2"]) == (set(), 0)
    assert listed(client, h["dept_icu"], hospital_id=w["h2"]) == (set(), 0)
    assert listed(client, h["dept_icu"], department_id=scene["lab"]) == (set(), 0)
    assert listed(client, h["dept_icu"], q="S-LAB") == (set(), 0)          # search stays inside too
    assert listed(client, h["dept_icu"], q=scene["d"]["lab"]["qr_identifier"]) == (set(), 0)
    # inside the scope, filters keep working
    assert listed(client, h["tech_h1"], department_id=scene["lab"]) == ({"S-LAB"}, 1)
    assert listed(client, h["admin"], hospital_id=w["h2"]) == ({"S-H2"}, 1)


def test_department_user_without_department_gets_department_required(client, scene):
    h, d = scene["h"], scene["d"]
    for url in (f"{API}/devices", f"{API}/devices/{d['icu']['id']}", f"{API}/devices/qr/{d['icu']['qr_identifier']}"):
        r = client.get(url, headers=h["dept_none"])
        assert r.status_code == 403, url
        assert r.json()["error"] == {"code": "department_required", "message": DEPARTMENT_REQUIRED}
    # the rule wins over every filter/flag (never falls back to hospital or organization scope)
    assert client.get(f"{API}/devices", headers=h["dept_none"], params={"hospital_id": scene["world"]["h1"]}).status_code == 403


# ---- T2: get by ID -----------------------------------------------------------------------------
@pytest.mark.parametrize("who,device,expected", [
    ("admin", "h2", 200), ("admin", "lab", 200), ("admin", "icu", 200),
    ("eng_h1", "h2", 404), ("eng_h1", "lab", 200), ("eng_h1", "icu", 200),
    ("tech_h1", "h2", 404), ("tech_h1", "lab", 200), ("tech_h1", "icu", 200),
    ("eng_h2", "icu", 404), ("tech_h2", "lab", 404), ("tech_h2", "h2", 200),
    ("dept_icu", "h2", 404), ("dept_icu", "lab", 404), ("dept_icu", "icu", 200),
])
def test_device_by_id_follows_the_scope(client, scene, who, device, expected):
    r = client.get(f"{API}/devices/{scene['d'][device]['id']}", headers=scene["h"][who])
    assert r.status_code == expected
    if expected == 404:  # indistinguishable from a device that does not exist
        assert r.json()["error"] == {"code": "not_found", "message": "Device not found."}


def test_out_of_scope_and_missing_devices_look_identical(client, scene):
    import uuid
    h = scene["h"]["tech_h1"]
    hidden = client.get(f"{API}/devices/{scene['d']['h2']['id']}", headers=h)
    missing = client.get(f"{API}/devices/{uuid.uuid4()}", headers=h)
    assert hidden.status_code == missing.status_code == 404
    assert hidden.json() == missing.json()


# ---- T2: archived devices are admin-only in lists -------------------------------------------------
@pytest.mark.parametrize("who", ["dept_icu", "dept_none", "tech_h1", "eng_h1", "tech_h2", "eng_h2"])
def test_include_archived_is_admin_only(client, scene, who):
    r = client.get(f"{API}/devices", headers=scene["h"][who], params={"include_archived": True})
    assert r.status_code == 403
    expected = "department_required" if who == "dept_none" else "forbidden"
    assert r.json()["error"]["code"] == expected


def test_admin_can_include_archived_and_default_lists_hide_them(client, scene):
    h = scene["h"]
    assert listed(client, h["admin"], include_archived=True) == ({"S-ICU", "S-LAB", "S-H2", "S-ARCH"}, 4)
    for who in ("admin", "tech_h1", "dept_icu"):
        assert "S-ARCH" not in listed(client, h[who])[0]
    # include_archived=false is the default and is allowed for everyone
    assert listed(client, h["tech_h1"], include_archived=False) == ({"S-ICU", "S-LAB"}, 2)


# ---- T3: QR exception ----------------------------------------------------------------------------
LIMITED_FIELDS = {
    "access", "id", "device_code", "name", "qr_identifier", "status", "is_archived",
    "hospital_id", "hospital_name", "department_id", "department_name", "location_id", "location",
    "model_name", "manufacturer_name", "category_name",
}
RESTRICTED = {
    "serial_number", "criticality", "current_risk_level", "installation_date", "warranty_expiry",
    "next_maintenance_due_date", "created_at", "updated_at", "organization_id",
    "device_model_id", "manufacturer_id", "category_id",
}


def qr(client, scene, who, device):
    return client.get(f"{API}/devices/qr/{scene['d'][device]['qr_identifier']}", headers=scene["h"][who])


def test_department_user_gets_a_limited_view_of_another_departments_device(client, scene):
    r = qr(client, scene, "dept_icu", "lab")
    assert r.status_code == 200
    body = r.json()
    assert body["access"] == "limited"
    assert set(body) == LIMITED_FIELDS                      # exactly these keys...
    assert not (set(body) & RESTRICTED)                     # ...restricted ones ABSENT, not null
    assert "SN-SECRET-2" not in r.text and "critical" not in r.text
    lab = scene["d"]["lab"]
    assert body["id"] == lab["id"] and body["device_code"] == "S-LAB" and body["name"] == "Lab analyser"
    assert body["department_name"] == "Lab" and body["hospital_name"] == lab["hospital_name"]
    assert body["model_name"] == lab["model_name"] and body["category_name"] == lab["category_name"]


def test_department_user_gets_the_normal_full_response_inside_their_department(client, scene):
    full = qr(client, scene, "dept_icu", "icu").json()
    assert "access" not in full                             # existing contract unchanged
    assert full == client.get(f"{API}/devices/{scene['d']['icu']['id']}", headers=scene["h"]["dept_icu"]).json()
    assert full["serial_number"] == "SN-SECRET-1" and full["criticality"] == "critical"


@pytest.mark.parametrize("who", ["admin", "eng_h1", "tech_h1"])
def test_other_roles_get_the_full_response_within_their_scope(client, scene, who):
    body = qr(client, scene, who, "lab").json()
    assert "access" not in body and body["serial_number"] == "SN-SECRET-2" and RESTRICTED <= set(body)


@pytest.mark.parametrize("who,device,expected", [
    ("dept_icu", "h2", 404), ("tech_h1", "h2", 404), ("eng_h1", "h2", 404), ("admin", "h2", 200),
    ("tech_h2", "icu", 404), ("eng_h2", "lab", 404), ("tech_h2", "h2", 200),
])
def test_qr_never_crosses_hospitals_except_for_admin(client, scene, who, device, expected):
    r = qr(client, scene, who, device)
    assert r.status_code == expected
    if expected == 404:
        assert r.json()["error"] == {"code": "not_found", "message": "No device found for this QR code."}


def test_limited_view_does_not_unlock_the_device_elsewhere(client, scene):
    h, lab = scene["h"]["dept_icu"], scene["d"]["lab"]
    assert qr(client, scene, "dept_icu", "lab").status_code == 200
    assert client.get(f"{API}/devices/{lab['id']}", headers=h).status_code == 404     # not by ID
    assert lab["device_code"] not in listed(client, h)[0]                              # not in lists
    assert client.patch(f"{API}/devices/{lab['id']}", headers=h, json={"name": "x"}).status_code == 403  # role


def test_archived_devices_still_resolve_by_qr_within_scope(client, scene):
    arch = scene["d"]["archived"]["qr_identifier"]
    for who in ("dept_icu", "tech_h1", "admin"):  # archived device sits in H1 / ICU
        body = client.get(f"{API}/devices/qr/{arch}", headers=scene["h"][who]).json()
        assert body["is_archived"] is True and body["status"] == "decommissioned"
    assert client.get(f"{API}/devices/qr/{arch}", headers=scene["h"]["tech_h2"]).status_code == 404


def test_qr_lookup_keeps_using_the_unique_index_shape():
    """The CP3 hospital condition is added to the CP1 query; the column is still compared directly."""
    import uuid
    from sqlalchemy.dialects import postgresql
    from app.repositories.device_repository import DeviceRepository
    stmt = DeviceRepository.qr_lookup_statement(uuid.uuid4(), ["QR-1", "qr-1"], uuid.uuid4())
    sql = str(stmt.compile(dialect=postgresql.dialect())).lower()
    assert "devices.qr_identifier in" in sql and "devices.hospital_id =" in sql and "upper(" not in sql


def test_openapi_documents_both_qr_shapes(client):
    schema = client.get("/openapi.json").json()
    op = schema["paths"]["/api/v1/devices/qr/{qr_identifier}"]["get"]
    refs = str(op["responses"]["200"]["content"]["application/json"]["schema"])
    assert "DeviceResponse" in refs and "DeviceSummaryResponse" in refs


# ---- T4: device writes -----------------------------------------------------------------------------
def body(scene, **over):
    w, c = scene["world"], scene["cat"]
    import uuid
    return {**dict(hospital_id=w["h1"], department_id=w["icu"], device_model_id=c["model_a"],
                   device_code=f"W-{uuid.uuid4().hex[:6]}", name="New device"), **over}


def test_engineer_creates_only_in_their_own_hospital(client, scene):
    h, w = scene["h"], scene["world"]
    r = client.post(f"{API}/devices", headers=h["eng_h1"], json=body(scene, hospital_id=w["h2"], department_id=w["rad"]))
    assert r.status_code == 400 and r.json()["error"]["message"] == "Hospital does not exist in your organization."
    # ...the very same answer as a hospital id that does not exist at all
    import uuid
    ghost = client.post(f"{API}/devices", headers=h["eng_h1"], json=body(scene, hospital_id=str(uuid.uuid4())))
    assert ghost.status_code == r.status_code and ghost.json() == r.json()
    # department / location of another hospital are refused (existing placement rules)
    r = client.post(f"{API}/devices", headers=h["eng_h1"], json=body(scene, department_id=w["rad"]))
    assert r.status_code == 400 and "Department does not belong" in r.json()["error"]["message"]
    loc_h2 = client.post(f"{API}/locations", headers=h["admin"], json=dict(hospital_id=w["h2"], room="H2-1")).json()
    r = client.post(f"{API}/devices", headers=h["eng_h1"], json=body(scene, location_id=loc_h2["id"]))
    assert r.status_code == 400 and "Location does not belong" in r.json()["error"]["message"]
    # own hospital works, and the H2 engineer can create in H2
    assert client.post(f"{API}/devices", headers=h["eng_h1"], json=body(scene)).status_code == 201
    assert client.post(f"{API}/devices", headers=h["eng_h2"],
                       json=body(scene, hospital_id=w["h2"], department_id=w["rad"])).status_code == 201


def test_engineer_cannot_update_or_archive_another_hospitals_device(client, scene):
    h, d = scene["h"], scene["d"]
    assert client.patch(f"{API}/devices/{d['h2']['id']}", headers=h["eng_h1"], json={"name": "hijack"}).status_code == 404
    assert client.delete(f"{API}/devices/{d['h2']['id']}", headers=h["eng_h1"]).status_code == 404
    still = client.get(f"{API}/devices/{d['h2']['id']}", headers=h["admin"]).json()
    assert still["name"] == "H2 scanner" and still["is_archived"] is False
    # in their own hospital the engineer keeps full write access
    assert client.patch(f"{API}/devices/{d['lab']['id']}", headers=h["eng_h1"], json={"name": "Lab analyser 2"}).status_code == 200


def test_engineer_cannot_move_a_device_out_of_their_hospital(client, scene):
    h, d, w = scene["h"], scene["d"], scene["world"]
    assert client.patch(f"{API}/devices/{d['icu']['id']}", headers=h["eng_h1"], json={"hospital_id": w["h2"]}).status_code == 422
    r = client.patch(f"{API}/devices/{d['icu']['id']}", headers=h["eng_h1"], json={"department_id": w["rad"]})
    assert r.status_code == 400 and "Department does not belong" in r.json()["error"]["message"]
    # moving between departments of their own hospital is fine
    assert client.patch(f"{API}/devices/{d['icu']['id']}", headers=h["eng_h1"], json={"department_id": scene["lab"]}).status_code == 200


def test_admin_keeps_organization_wide_writes(client, scene):
    h, d, w = scene["h"], scene["d"], scene["world"]
    assert client.post(f"{API}/devices", headers=h["admin"], json=body(scene, hospital_id=w["h2"], department_id=w["rad"])).status_code == 201
    assert client.patch(f"{API}/devices/{d['h2']['id']}", headers=h["admin"], json={"name": "H2 scanner v2"}).status_code == 200
    assert client.delete(f"{API}/devices/{d['h2']['id']}", headers=h["admin"]).status_code == 200


@pytest.mark.parametrize("who", ["tech_h1", "dept_icu", "dept_none"])
def test_existing_write_role_restrictions_are_unchanged(client, scene, who):
    h, d = scene["h"], scene["d"]
    assert client.post(f"{API}/devices", headers=h[who], json=body(scene)).status_code == 403
    assert client.patch(f"{API}/devices/{d['icu']['id']}", headers=h[who], json={"name": "x"}).status_code == 403
    assert client.delete(f"{API}/devices/{d['icu']['id']}", headers=h[who]).status_code == 403


# ---- T5: structure reads -------------------------------------------------------------------------
def names(client, headers, path, **params):
    r = client.get(f"{API}/{path}", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return {i.get("code") or i.get("name") or i.get("room") for i in r.json()["items"]}, r.json()["total"]


@pytest.fixture
def h2_location(client, scene):
    w = scene["world"]
    a = scene["h"]["admin"]
    loc1 = client.post(f"{API}/locations", headers=a, json=dict(hospital_id=w["h1"], room="R-H1")).json()
    loc2 = client.post(f"{API}/locations", headers=a, json=dict(hospital_id=w["h2"], room="R-H2")).json()
    return loc1, loc2


@pytest.mark.parametrize("who", ["dept_icu", "dept_none", "tech_h1", "eng_h1"])
def test_non_admins_see_only_their_own_hospitals_structure(client, scene, h2_location, who):
    h, w = scene["h"][who], scene["world"]
    loc_h1, loc_h2 = h2_location
    assert names(client, h, "hospitals") == ({"H1"}, 1)
    assert names(client, h, "departments") == ({"ICU", "Lab"}, 2)        # all departments of OWN hospital
    assert names(client, h, "locations") == ({"R-H1"}, 1)
    # query parameters cannot widen it
    assert names(client, h, "departments", hospital_id=w["h2"]) == (set(), 0)
    assert names(client, h, "locations", hospital_id=w["h2"]) == (set(), 0)
    # IDs cannot bypass it: 404, identical to a missing record
    for path, msg in ((f"hospitals/{w['h2']}", "Hospital not found."), (f"departments/{w['rad']}", "Department not found."),
                      (f"locations/{loc_h2['id']}", "Location not found.")):
        r = client.get(f"{API}/{path}", headers=h)
        assert r.status_code == 404 and r.json()["error"] == {"code": "not_found", "message": msg}, path
    for path in (f"hospitals/{w['h1']}", f"departments/{w['icu']}", f"departments/{scene['lab']}", f"locations/{loc_h1['id']}"):
        assert client.get(f"{API}/{path}", headers=h).status_code == 200, path


def test_h2_staff_see_only_h2_structure(client, scene, h2_location):
    h = scene["h"]["tech_h2"]
    assert names(client, h, "hospitals") == ({"H2"}, 1)
    assert names(client, h, "departments") == ({"Radiology"}, 1)
    assert names(client, h, "locations") == ({"R-H2"}, 1)


def test_admin_structure_reads_stay_organization_wide(client, scene, h2_location):
    a, w = scene["h"]["admin"], scene["world"]
    assert names(client, a, "hospitals") == ({"H1", "H2"}, 2)
    assert names(client, a, "departments") == ({"ICU", "Lab", "Radiology"}, 3)
    assert names(client, a, "locations") == ({"R-H1", "R-H2"}, 2)
    assert names(client, a, "departments", hospital_id=w["h2"]) == ({"Radiology"}, 1)
    assert client.get(f"{API}/hospitals/{w['h2']}", headers=a).status_code == 200


def test_department_users_get_only_the_existing_minimal_department_fields(client, scene):
    item = client.get(f"{API}/departments", headers=scene["h"]["dept_icu"]).json()["items"][0]
    admin_item = client.get(f"{API}/departments/{item['id']}", headers=scene["h"]["admin"]).json()
    assert set(item) == set(admin_item)  # same existing contract, nothing extra for anyone


def test_structure_writes_are_still_admin_only(client, scene):
    w = scene["world"]
    for who in ("eng_h1", "tech_h1", "dept_icu"):
        h = scene["h"][who]
        assert client.post(f"{API}/departments", headers=h, json={"hospital_id": w["h1"], "name": "X"}).status_code == 403
        assert client.patch(f"{API}/hospitals/{w['h1']}", headers=h, json={"name": "X"}).status_code == 403
