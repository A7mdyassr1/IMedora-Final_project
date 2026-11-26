"""Shared B6 test scenario (tests only): the B4 `tickets` scene plus risk / QA helpers and cleanup.

`rq` depends on `tickets`, so pytest tears it down FIRST: it deletes, for the test's two
organizations only, the QA records and risk assessments the test created (both RESTRICT devices,
hospitals and users). Deleting assessments fires the risk trigger, which only rewrites the test's
own devices' cached level. Devices, users, audit rows and the rest are then removed by the
existing fixtures (`tickets`, `cat`, `world`), unchanged.

Devices of the scene (tests/scope_scene.py): icu (H1/ICU), lab (H1/Lab), h2 (H2/Radiology),
archived (H1/ICU, archived). Users: admin, eng_h1, eng_h2, tech_h1, tech_h2, dept_icu, dept_none.
"""
import uuid

import pytest
from sqlalchemy import text

from app.core.database import get_session_factory
from tests.world import API


@pytest.fixture
def rq(tickets, client):
    d = tickets["d"]

    def device_id(key_or_id):
        return d[key_or_id]["id"] if key_or_id in d else key_or_id

    def assess(headers, device, risk_level="medium", **extra):
        return client.post(f"{API}/risk-assessments", headers=headers,
                           json={"device_id": device_id(device), "risk_level": risk_level, **extra})

    def correct(headers, assessment_id, **body):
        return client.patch(f"{API}/risk-assessments/{assessment_id}", headers=headers, json=body)

    def level(device):
        """devices.current_risk_level straight from the database (what the trigger wrote)."""
        return tickets["sql"]("SELECT current_risk_level::text FROM devices WHERE id = :d", d=device_id(device))[0][0]

    def set_status(device, status):
        tickets["sql"]("UPDATE devices SET status = CAST(:s AS device_status) WHERE id = :d", s=status, d=device_id(device))

    def set_hospital_active(hospital_key, active):
        tickets["sql"]("UPDATE hospitals SET is_active = :a WHERE id = :h", a=active, h=tickets["world"][hospital_key])

    yield dict(tickets, device_id=device_id, assess=assess, correct=correct, level=level, set_status=set_status,
               set_hospital_active=set_hospital_active)

    with get_session_factory()() as db:
        orgs = [uuid.UUID(tickets["world"]["org"]), uuid.UUID(tickets["world"]["other"])]
        for table in ("qa_records", "risk_assessments"):
            db.execute(text(f"DELETE FROM {table} WHERE organization_id = ANY(:o)"), {"o": orgs})
        db.execute(text("UPDATE hospitals SET is_active = true WHERE organization_id = ANY(:o)"), {"o": orgs})
        db.commit()
