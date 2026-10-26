"""
Authorization rules for every B3 endpoint, checked WITHOUT a database:
the role check happens (and fails) before any query runs.

  read   -> any authenticated user
  hospitals / departments / locations / organization writes -> admin only
  devices + catalog writes -> admin or biomedical_engineer
"""
import uuid
from types import SimpleNamespace

import pytest

from app.api.deps import get_current_user

ID = uuid.uuid4()

ADMIN_ONLY_WRITES = [
    ("post", "/api/v1/hospitals"),
    ("patch", f"/api/v1/hospitals/{ID}"),
    ("post", "/api/v1/departments"),
    ("patch", f"/api/v1/departments/{ID}"),
    ("delete", f"/api/v1/departments/{ID}"),
    ("post", "/api/v1/locations"),
    ("patch", f"/api/v1/locations/{ID}"),
    ("delete", f"/api/v1/locations/{ID}"),
    ("patch", "/api/v1/organizations/current"),
]

ASSET_WRITES = [
    ("post", "/api/v1/devices"),
    ("patch", f"/api/v1/devices/{ID}"),
    ("delete", f"/api/v1/devices/{ID}"),
    ("post", "/api/v1/device-categories"),
    ("patch", f"/api/v1/device-categories/{ID}"),
    ("delete", f"/api/v1/device-categories/{ID}"),
    ("post", "/api/v1/manufacturers"),
    ("patch", f"/api/v1/manufacturers/{ID}"),
    ("delete", f"/api/v1/manufacturers/{ID}"),
    ("post", "/api/v1/device-models"),
    ("patch", f"/api/v1/device-models/{ID}"),
    ("delete", f"/api/v1/device-models/{ID}"),
]

READS = [
    "/api/v1/organizations/current",
    "/api/v1/hospitals", f"/api/v1/hospitals/{ID}",
    "/api/v1/departments", f"/api/v1/departments/{ID}",
    "/api/v1/locations", f"/api/v1/locations/{ID}",
    "/api/v1/device-categories", "/api/v1/manufacturers", "/api/v1/device-models",
    "/api/v1/devices", f"/api/v1/devices/{ID}", "/api/v1/devices/qr/IMD-123",
]


def login_as(app, role):
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=uuid.uuid4(), organization_id=uuid.uuid4(), role=SimpleNamespace(name=role)
    )


@pytest.mark.parametrize("path", READS)
def test_every_read_requires_authentication(client, path):
    r = client.get(path)
    assert r.status_code == 401 and r.json()["error"]["code"] == "unauthorized"


@pytest.mark.parametrize("method, path", ADMIN_ONLY_WRITES)
@pytest.mark.parametrize("role", ["biomedical_engineer", "technician", "department_user"])
def test_structure_writes_are_admin_only(app, client, method, path, role):
    login_as(app, role)
    r = client.request(method.upper(), path, json={})
    assert r.status_code == 403, f"{role} {method.upper()} {path}"


@pytest.mark.parametrize("method, path", ASSET_WRITES)
@pytest.mark.parametrize("role", ["technician", "department_user"])
def test_device_and_catalog_writes_need_admin_or_engineer(app, client, method, path, role):
    login_as(app, role)
    r = client.request(method.upper(), path, json={})
    assert r.status_code == 403, f"{role} {method.upper()} {path}"


@pytest.mark.parametrize("role", ["admin", "biomedical_engineer"])
def test_privileged_roles_pass_the_role_check(app, client, role):
    # Past authorization the empty body fails validation (422), proving the 403 gate was cleared.
    login_as(app, role)
    assert client.post("/api/v1/devices", json={}).status_code == 422
    assert client.post("/api/v1/device-models", json={}).status_code == 422


def test_openapi_contains_the_b3_routes(client):
    paths = client.get("/openapi.json").json()["paths"]
    for p in ("/api/v1/devices", "/api/v1/devices/qr/{qr_identifier}", "/api/v1/devices/{device_id}",
              "/api/v1/hospitals", "/api/v1/departments", "/api/v1/locations",
              "/api/v1/device-categories", "/api/v1/manufacturers", "/api/v1/device-models"):
        assert p in paths, p
