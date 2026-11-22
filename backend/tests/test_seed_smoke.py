"""
Seeded-data smoke tests (B3.1 CP3, T8) - OPT-IN, against a disposable SEEDED database only.

Runs only when TEST_SEED_DATABASE_URL is set, and refuses to run unless that URL names a database
called exactly `imedora_seedtest`. It never uses DATABASE_URL or TEST_DATABASE_URL, and the app under
test is bound to the seed database through a dependency override (the normal test database is not
touched).

One-time setup of the disposable database (from the repository root):

    createdb imedora_seedtest
    DATABASE_URL=postgresql+psycopg2://<user>:<pw>@localhost:5432/imedora_seedtest alembic upgrade head
    DATABASE_URL=postgresql+psycopg2://<user>:<pw>@localhost:5432/imedora_seedtest python database/seeds/run_all.py

Run (from backend/):

    TEST_SEED_DATABASE_URL=postgresql+psycopg2://<user>:<pw>@localhost:5432/imedora_seedtest pytest -q tests/test_seed_smoke.py

What it adds, and removes again in teardown (also when a test fails): uniquely named temporary users,
one temporary hospital + department (for the cross-hospital case), and any role rows that the seed
does not have (the seed only creates `technician`) - those are deleted only if this run created them.
The seed scripts and the permanent seed rows are never modified.
"""
import os
import uuid

import pytest
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

SEED_DB_NAME = "imedora_seedtest"
SEED_URL = os.environ.get("TEST_SEED_DATABASE_URL")

if not SEED_URL:
    pytest.skip(
        "Seed smoke tests are opt-in: set TEST_SEED_DATABASE_URL to a disposable, seeded database named "
        f"'{SEED_DB_NAME}' (see the module docstring for the setup commands).",
        allow_module_level=True,
    )

from fastapi.testclient import TestClient  # noqa: E402

from app.core.database import get_db  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import AuditLog, Department, Hospital, Organization, Role, User  # noqa: E402

API = "/api/v1"
PW = "Seed-Smoke-" + uuid.uuid4().hex[:10]


def _refuse_unless_disposable(url: str) -> None:
    parsed = make_url(url)
    if parsed.database != SEED_DB_NAME:
        pytest.fail(f"Refusing to run seed smoke tests: TEST_SEED_DATABASE_URL must name the disposable database "
                    f"'{SEED_DB_NAME}', not '{parsed.database}'.", pytrace=False)
    for other in ("TEST_DATABASE_URL", "DATABASE_URL"):
        value = os.environ.get(other)
        if value and make_url(value).database == parsed.database and make_url(value).host == parsed.host:
            pytest.fail(f"Refusing to run: TEST_SEED_DATABASE_URL points at the same database as {other}.", pytrace=False)


@pytest.fixture(scope="module")
def seed():
    _refuse_unless_disposable(SEED_URL)
    engine = create_engine(SEED_URL, pool_pre_ping=True)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    sfx = uuid.uuid4().hex[:8]
    created = {"users": [], "roles": [], "hospital": None, "department": None}
    try:
        with Session() as db:
            org = db.scalar(select(Organization).where(Organization.code == "CAIRO-MED"))
            hosp = db.scalar(select(Hospital).where(Hospital.code == "CMC-MAIN"))
            if org is None or hosp is None:
                pytest.skip("Seed data missing: run database/seeds/run_all.py against imedora_seedtest first.")
            devices = {r.device_code: r for r in db.execute(text(
                "SELECT d.id, d.device_code, d.qr_identifier, d.department_id, dep.name AS dept "
                "FROM devices d JOIN departments dep ON dep.id = d.department_id "
                "WHERE d.hospital_id = :h AND d.device_code IN ('DEV-001', 'DEV-002')"), {"h": hosp.id})}
            if set(devices) != {"DEV-001", "DEV-002"}:
                pytest.skip("Seed devices DEV-001 / DEV-002 not found in CMC-MAIN.")
            icu = devices["DEV-001"].department_id
            assert devices["DEV-002"].department_id != icu, "seed devices must sit in two departments"

            roles = {r.name: r.id for r in db.scalars(select(Role))}
            for name in ("department_user", "technician"):
                if name not in roles:
                    role = Role(name=name)
                    db.add(role)
                    db.flush()
                    roles[name] = role.id
                    created["roles"].append(role.id)

            other = Hospital(organization_id=org.id, name=f"Smoke Hospital {sfx}", code=f"SMK-{sfx}", is_active=True)
            db.add(other)
            db.flush()
            other_dept = Department(hospital_id=other.id, name=f"Smoke Dept {sfx}")
            db.add(other_dept)
            db.flush()
            created["hospital"], created["department"] = other.id, other_dept.id

            def add(key, role, hospital_id, department_id=None):
                u = User(organization_id=org.id, hospital_id=hospital_id, department_id=department_id,
                         role_id=roles[role], full_name=f"smoke {key}", email=f"smoke-{key}-{sfx}@seedtest.invalid",
                         password_hash=hash_password(PW), is_active=True)
                db.add(u)
                db.flush()
                created["users"].append(u.id)
                return u.email

            emails = dict(
                dept_icu=add("dept-icu", "department_user", hosp.id, icu),
                dept_none=add("dept-none", "department_user", hosp.id),
                tech=add("tech", "technician", hosp.id),
                tech_other=add("tech-other", "technician", other.id),
            )
            db.commit()

        app = create_app()

        def seed_db():
            s = Session()
            try:
                yield s
            except Exception:
                s.rollback()
                raise
            finally:
                s.close()

        app.dependency_overrides[get_db] = seed_db
        with TestClient(app) as client:
            headers = {}
            for key, email in emails.items():
                r = client.post(f"{API}/auth/login", json={"identifier": email, "password": PW})
                assert r.status_code == 200, r.text
                headers[key] = {"Authorization": f"Bearer {r.json()['access_token']}"}
            yield dict(client=client, h=headers, devices=devices, hospital_id=hosp.id, Session=Session)
    finally:
        with Session() as db:  # always runs, even after a failing test
            ids = created["users"]
            if ids:
                db.execute(delete(AuditLog).where(AuditLog.user_id.in_(ids)))
                db.execute(delete(User).where(User.id.in_(ids)))
            if created["department"]:
                db.execute(delete(Department).where(Department.id == created["department"]))
            if created["hospital"]:
                db.execute(delete(AuditLog).where(AuditLog.record_id == created["hospital"]))
                db.execute(delete(Hospital).where(Hospital.id == created["hospital"]))
            for role_id in created["roles"]:  # only roles this run created, and only if unused
                if not db.scalar(select(User.id).where(User.role_id == role_id).limit(1)):
                    db.execute(delete(Role).where(Role.id == role_id))
            db.commit()
        engine.dispose()


def test_department_user_resolves_another_departments_seed_device_as_limited(seed):
    c, d = seed["client"], seed["devices"]["DEV-002"]
    r = c.get(f"{API}/devices/qr/{d.qr_identifier}", headers=seed["h"]["dept_icu"])
    assert r.status_code == 200
    body = r.json()
    assert body["access"] == "limited" and body["device_code"] == "DEV-002" and body["department_name"] == d.dept
    for restricted in ("serial_number", "criticality", "current_risk_level", "next_maintenance_due_date",
                       "installation_date", "warranty_expiry", "created_at", "updated_at"):
        assert restricted not in body
    own = c.get(f"{API}/devices/qr/{seed['devices']['DEV-001'].qr_identifier}", headers=seed["h"]["dept_icu"]).json()
    assert "access" not in own and own["device_code"] == "DEV-001" and "criticality" in own


def test_department_user_cannot_open_that_device_by_id(seed):
    r = seed["client"].get(f"{API}/devices/{seed['devices']['DEV-002'].id}", headers=seed["h"]["dept_icu"])
    assert r.status_code == 404


def test_technician_sees_both_seed_devices_of_their_hospital(seed):
    r = seed["client"].get(f"{API}/devices", headers=seed["h"]["tech"], params={"page_size": 100})
    assert r.status_code == 200
    items = r.json()["items"]
    assert {"DEV-001", "DEV-002"} <= {i["device_code"] for i in items}
    assert {i["hospital_id"] for i in items} == {str(seed["hospital_id"])}


def test_department_user_without_department_is_refused(seed):
    c, h, d = seed["client"], seed["h"]["dept_none"], seed["devices"]["DEV-001"]
    for url in (f"{API}/devices", f"{API}/devices/{d.id}", f"{API}/devices/qr/{d.qr_identifier}"):
        r = c.get(url, headers=h)
        assert r.status_code == 403 and r.json()["error"]["code"] == "department_required", url


def test_cross_hospital_isolation(seed):
    c, h = seed["client"], seed["h"]["tech_other"]
    assert c.get(f"{API}/devices", headers=h).json()["total"] == 0
    for code in ("DEV-001", "DEV-002"):
        d = seed["devices"][code]
        assert c.get(f"{API}/devices/{d.id}", headers=h).status_code == 404
        assert c.get(f"{API}/devices/qr/{d.qr_identifier}", headers=h).status_code == 404
    assert c.get(f"{API}/hospitals/{seed['hospital_id']}", headers=h).status_code == 404


def test_seeded_placeholder_technician_cannot_log_in(seed):
    with seed["Session"]() as db:
        stored = db.scalar(select(User.password_hash).where(User.email == "mostafa.tech@cairomed.example"))
    if stored != "not-a-real-hash":
        pytest.skip("The seeded technician's password was already initialised in this database.")
    for attempt in ("not-a-real-hash", "", "password", PW):
        r = seed["client"].post(f"{API}/auth/login", json={"identifier": "mostafa.tech@cairomed.example", "password": attempt or "x"})
        assert r.status_code == 401 and r.json()["error"]["message"] == "Invalid email or password."
