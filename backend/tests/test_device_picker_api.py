"""B8 CP2 - the mobile device picker: `GET /devices?q=` finds devices by name, device code AND department
name (Master Instructions section 5), always inside the caller's scope. Real PostgreSQL; skipped unless
TEST_DATABASE_URL is set.
"""
from tests.scope_scene import scene  # noqa: F401
from tests.test_devices_flow import cat  # noqa: F401
from tests.world import API


def _codes(client, headers, q, **params):
    r = client.get(f"{API}/devices", headers=headers, params={"q": q, "page_size": 100, **params})
    assert r.status_code == 200, r.text
    return sorted(d["device_code"] for d in r.json()["items"])


def test_search_by_department_name(client, scene):
    h = scene["h"]
    # "H2 scanner" (S-H2) is in Radiology: only its department name matches "radio"
    assert _codes(client, h["admin"], "radio") == ["S-H2"]
    assert _codes(client, h["admin"], "RADIOLOGY") == ["S-H2"]          # case-insensitive, like the other fields
    assert _codes(client, h["admin"], "lab") == ["S-LAB"]
    # name and code still work, and the department matches add to them
    assert _codes(client, h["admin"], "ventilator") == ["S-ICU"]
    assert _codes(client, h["admin"], "S-H2") == ["S-H2"]
    assert _codes(client, h["admin"], "ICU") == ["S-ICU"]               # name and department: listed once


def test_search_stays_inside_the_callers_scope(client, scene):
    h = scene["h"]
    assert _codes(client, h["eng_h1"], "radio") == []                   # another hospital's department
    assert _codes(client, h["tech_h2"], "radio") == ["S-H2"]
    assert _codes(client, h["dept_icu"], "lab") == []                   # another department of the same hospital
    assert _codes(client, h["dept_icu"], "icu") == ["S-ICU"]
    # archived devices stay hidden unless an admin asks for them
    assert _codes(client, h["admin"], "icu", include_archived="true") == ["S-ARCH", "S-ICU"]
