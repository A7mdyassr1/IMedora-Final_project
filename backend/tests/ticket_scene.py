"""Shared B4 test scenario (tests only): the CP3 `scene` plus ticket helpers and cleanup.

`tickets` depends on `scene`, so pytest tears it down BEFORE `scene`'s fixtures (`cat` removes
devices, `world` removes users and audit rows). It deletes, bottom-up and only for the test's two
organizations, every maintenance row the test created: records and schedules (RESTRICT devices
and tickets), then tickets (their assignments cascade), then the test's own maintenance types
(global table; names end in the test's unique suffix). B5 adds: parts usage (cascades with the
records), the organizations' stock rows and the test's own catalog parts. The existing fixtures
are unchanged.
"""
import uuid

import pytest
from sqlalchemy import select, text

from app.core.database import get_session_factory
from app.core.security import hash_password
from app.models import Role, User
from tests.world import API, PW, auth


@pytest.fixture
def tickets(scene, client):
    world = scene["world"]

    def report(headers, device_key_or_id, category="Power issue", description="The device won't turn on", **extra):
        device_id = scene["d"][device_key_or_id]["id"] if device_key_or_id in scene["d"] else device_key_or_id
        return client.post(f"{API}/tickets", headers=headers,
                           json={"device_id": device_id, "category": category, "description": description, **extra})

    def add_user(email_key, role, hospital_key, department_id=None):
        with get_session_factory()() as db:
            role_id = db.scalar(select(Role.id).where(Role.name == role))
            email = f"{email_key}-{world['sfx']}@b2.test"
            db.add(User(organization_id=world["org"], hospital_id=world[hospital_key], department_id=department_id,
                        role_id=role_id, full_name=email_key, email=email, password_hash=hash_password(PW), is_active=True))
            db.commit()
        return auth(client, email)

    def sql(statement, **params):
        with get_session_factory()() as db:
            result = db.execute(text(statement), params)
            rows = result.fetchall() if result.returns_rows else None
            db.commit()
            return rows

    type_name = f"test-corrective-{world['sfx']}"

    def record(ticket_id, description="Replaced the power supply"):
        """B4 CP2: a maintenance record linked to the ticket, inserted directly (the records API
        arrives in CP3). Uses a per-test maintenance type, removed again at teardown."""
        type_id = (sql("SELECT id::text FROM maintenance_types WHERE name = :n", n=type_name) or
                   sql("INSERT INTO maintenance_types (name) VALUES (:n) RETURNING id::text", n=type_name))[0][0]
        return sql("INSERT INTO maintenance_records (organization_id, hospital_id, device_id, maintenance_type_id, ticket_id, "
                   "performed_by, description) SELECT organization_id, hospital_id, device_id, :mt, id, :u, :d "
                   "FROM maintenance_tickets WHERE id = :t RETURNING id::text",
                   mt=type_id, u=world["tech_id"], d=description, t=ticket_id)[0][0]

    def mtype(name):
        """B4 CP3: a maintenance type created through the admin API (unique per test, removed at teardown)."""
        r = client.post(f"{API}/maintenance-types", headers=scene["h"]["admin"], json={"name": f"{name}-{world['sfx']}"})
        assert r.status_code == 201, r.text
        return r.json()["id"]

    yield dict(scene, report=report, add_user=add_user, sql=sql, record=record, mtype=mtype)

    with get_session_factory()() as db:
        orgs = [uuid.UUID(world["org"]), uuid.UUID(world["other"])]
        # B5: attachments first (they RESTRICT tickets, records, devices and users); their files live in
        # the session's temporary STORAGE_DIR (tests/conftest.py)
        db.execute(text("DELETE FROM attachments WHERE organization_id = ANY(:o)"), {"o": orgs})
        # B5: parts usage goes with its records (ON DELETE CASCADE; the trigger gives the stock back)
        for table in ("maintenance_records", "maintenance_schedules", "maintenance_tickets"):
            db.execute(text(f"DELETE FROM {table} WHERE organization_id = ANY(:o)"), {"o": orgs})
        # B5: the test organizations' stock rows, then the test's own catalog parts (global table;
        # part numbers contain the test's unique suffix)
        db.execute(text("DELETE FROM part_inventory WHERE organization_id = ANY(:o)"), {"o": orgs})
        db.execute(text("DELETE FROM parts WHERE part_number ILIKE :p"), {"p": f"%{world['sfx']}%"})
        db.execute(text("DELETE FROM maintenance_types WHERE name = :n OR name LIKE :p"),
                   {"n": type_name, "p": f"%-{world['sfx']}"})
        db.commit()
