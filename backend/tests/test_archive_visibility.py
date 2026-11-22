"""
Archive visibility by role (B3.1 CP3, T6) against REAL PostgreSQL. Skipped unless TEST_DATABASE_URL is set.

Policy (Decision 6 + CP3 Decision 3):
- `deleted_at` = archived (device status `decommissioned`); `is_active` = inactive (hospitals, users).
- Ordinary lists hide archived devices; only admins may ask for them (include_archived=true),
  every other role gets 403 (never silently ignored).
- An archived device stays readable by ID / QR inside the caller's scope (history), is read-only,
  and is still 404 outside the scope.
"""
import pytest

from tests.scope_scene import scene  # noqa: F401  (pytest fixture)
from tests.test_devices_flow import cat  # noqa: F401  (pytest fixture)
from tests.world import API

NON_ADMINS = ["dept_icu", "dept_none", "tech_h1", "eng_h1", "tech_h2", "eng_h2"]


def codes(client, headers, **params):
    r = client.get(f"{API}/devices", headers=headers, params=params)
    return r.status_code, {i["device_code"] for i in r.json().get("items", [])}


@pytest.mark.parametrize("who", ["admin", "dept_icu", "tech_h1", "eng_h1"])
def test_ordinary_lists_hide_archived_devices_for_every_role(client, scene, who):
    status, found = codes(client, scene["h"][who])
    assert status == 200 and "S-ARCH" not in found


@pytest.mark.parametrize("who", NON_ADMINS)
def test_include_archived_is_refused_for_non_admins(client, scene, who):
    r = client.get(f"{API}/devices", headers=scene["h"][who], params={"include_archived": "true"})
    assert r.status_code == 403
    if who != "dept_none":  # dept_none is refused earlier, with department_required
        assert r.json()["error"] == {"code": "forbidden", "message": "Only administrators can include archived devices."}


def test_admin_sees_archived_devices_only_when_asking(client, scene):
    a = scene["h"]["admin"]
    assert "S-ARCH" in codes(client, a, include_archived=True)[1]
    assert "S-ARCH" not in codes(client, a)[1]
    # admin + include_archived still applies other filters
    assert codes(client, a, include_archived=True, hospital_id=scene["world"]["h2"])[1] == {"S-H2"}


@pytest.mark.parametrize("who,expected", [("admin", 200), ("eng_h1", 200), ("tech_h1", 200), ("dept_icu", 200),
                                          ("tech_h2", 404), ("eng_h2", 404), ("dept_none", 403)])
def test_archived_device_by_id_follows_the_normal_scope(client, scene, who, expected):
    r = client.get(f"{API}/devices/{scene['d']['archived']['id']}", headers=scene["h"][who])
    assert r.status_code == expected
    if expected == 200:
        assert r.json()["is_archived"] is True and r.json()["status"] == "decommissioned"


def test_out_of_scope_archived_device_is_a_plain_404(client, scene):
    a, h2 = scene["h"]["admin"], scene["d"]["h2"]
    assert client.delete(f"{API}/devices/{h2['id']}", headers=a).status_code == 200   # archive the H2 device
    r = client.get(f"{API}/devices/{h2['id']}", headers=scene["h"]["tech_h1"])
    assert r.status_code == 404 and r.json()["error"]["message"] == "Device not found."
    assert client.get(f"{API}/devices/qr/{h2['qr_identifier']}", headers=scene["h"]["tech_h1"]).status_code == 404


def test_archived_devices_stay_read_only(client, scene):
    arch = scene["d"]["archived"]["id"]
    for who in ("admin", "eng_h1"):
        r = client.patch(f"{API}/devices/{arch}", headers=scene["h"][who], json={"name": "revive"})
        assert r.status_code == 400 and r.json()["error"]["message"] == "Archived devices cannot be modified."
    # archiving again is idempotent and changes nothing
    again = client.delete(f"{API}/devices/{arch}", headers=scene["h"]["admin"])
    assert again.status_code == 200 and again.json()["is_archived"] is True


def test_archived_is_not_the_same_as_inactive(client, scene):
    """A device in an INACTIVE hospital is not archived: it stays in admin lists (no flag needed),
    is_archived stays false, and it is not counted among archived devices."""
    a, w = scene["h"]["admin"], scene["world"]
    assert client.patch(f"{API}/hospitals/{w['h2']}", headers=a, json={"is_active": False}).status_code == 200
    status, found = codes(client, a)
    assert status == 200 and "S-H2" in found and "S-ARCH" not in found
    h2 = client.get(f"{API}/devices/{scene['d']['h2']['id']}", headers=a).json()
    assert h2["is_archived"] is False and h2["status"] == "active"
    hosp = client.get(f"{API}/hospitals/{w['h2']}", headers=a).json()
    assert hosp["is_active"] is False  # inactive hospital, active (not archived) device
