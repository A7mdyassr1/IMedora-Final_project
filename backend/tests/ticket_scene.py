"""Shared B4 test scenario (tests only): the CP3 `scene` plus ticket helpers and cleanup.

`tickets` depends on `scene`, so pytest tears it down BEFORE `scene`'s fixtures (`cat` removes
devices, `world` removes users and audit rows). It deletes, bottom-up and only for the test's two
organizations, every maintenance row the test created: records and schedules (RESTRICT devices
and tickets), then tickets (their assignments cascade). The existing fixtures are unchanged.
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

    yield dict(scene, report=report, add_user=add_user, sql=sql)

    with get_session_factory()() as db:
        orgs = [uuid.UUID(world["org"]), uuid.UUID(world["other"])]
        for table in ("maintenance_records", "maintenance_schedules", "maintenance_tickets"):
            db.execute(text(f"DELETE FROM {table} WHERE organization_id = ANY(:o)"), {"o": orgs})
        db.commit()
