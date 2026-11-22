"""Ticket number = TKT-{first 8 hex of the UUID, upper-case} (B3.1 CP2, Option A). No database.

There are no ticket endpoints until B4, so the API-level checks below use a throwaway FastAPI
app with response schemas built on TicketNumberMixin, exactly as B4's ticket schemas will be.
B4 adds the real detail/list endpoint tests.
"""
import uuid
from types import SimpleNamespace
from typing import List

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import database
from app.schemas.ticket import TicketNumberMixin
from app.utils.ticket_number import TICKET_NUMBER_PATTERN, ticket_number

KNOWN = uuid.UUID("3f9a1c2b-7d4e-4a1b-9c3d-2e5f6a7b8c9d")


# ---- the helper ----------------------------------------------------------------------------
def test_format_is_tkt_dash_eight_uppercase_hex():
    n = ticket_number(KNOWN)
    assert n == "TKT-3F9A1C2B"
    assert TICKET_NUMBER_PATTERN.fullmatch(n)


def test_derived_from_the_first_eight_hex_characters_of_the_uuid():
    for _ in range(200):
        u = uuid.uuid4()
        assert ticket_number(u) == "TKT-" + str(u).replace("-", "")[:8].upper()
        assert TICKET_NUMBER_PATTERN.fullmatch(ticket_number(u))


def test_same_ticket_always_gets_the_same_number():
    assert {ticket_number(KNOWN) for _ in range(5)} == {"TKT-3F9A1C2B"}
    assert ticket_number(str(KNOWN)) == ticket_number(str(KNOWN).upper()) == ticket_number(KNOWN)


def test_invalid_ids_are_rejected():
    for bad in ("", "not-a-uuid", "TKT-3F9A1C2B"):
        with pytest.raises(ValueError):
            ticket_number(bad)


def test_numbering_needs_no_database(monkeypatch):
    def no_db(*a, **k):
        raise AssertionError("ticket numbering must not touch the database")
    monkeypatch.setattr(database, "get_engine", no_db)
    monkeypatch.setattr(database, "get_session_factory", no_db)
    assert ticket_number(KNOWN) == "TKT-3F9A1C2B"


# ---- the reusable schema mixin -----------------------------------------------------------------
class DemoTicket(TicketNumberMixin):  # shape of a future B4 TicketResponse
    status: str
    problem_description: str


def _orm_row(**kw):  # stands in for a MaintenanceTicket ORM row (from_attributes)
    return SimpleNamespace(**{"id": KNOWN, "status": "open", "problem_description": "[Power issue] Off", **kw})


def test_mixin_adds_number_next_to_the_unchanged_uuid():
    t = DemoTicket.model_validate(_orm_row(), from_attributes=True)
    dumped = t.model_dump(mode="json")
    assert dumped["id"] == str(KNOWN)          # the identifier is untouched
    assert dumped["number"] == "TKT-3F9A1C2B"
    assert t.number == ticket_number(t.id)


def test_number_cannot_be_supplied_or_overridden_by_input():
    t = DemoTicket.model_validate({"id": str(KNOWN), "status": "open", "problem_description": "x", "number": "TKT-HACKED"})
    assert t.number == "TKT-3F9A1C2B"


def test_number_is_read_only_in_the_openapi_schema():
    schema = DemoTicket.model_json_schema(mode="serialization")
    assert schema["properties"]["number"]["readOnly"] is True
    assert "number" not in DemoTicket.model_json_schema(mode="validation")["properties"]


# ---- API responses (detail + list), as B4 will expose them --------------------------------------
@pytest.fixture
def demo_api():
    other = uuid.UUID("00000000-0000-4000-8000-0000000000ab")
    rows = {KNOWN: _orm_row(), other: _orm_row(id=other, status="resolved")}
    app = FastAPI()

    @app.get("/tickets/{ticket_id}", response_model=DemoTicket)
    def detail(ticket_id: uuid.UUID):
        return DemoTicket.model_validate(rows[ticket_id], from_attributes=True)

    @app.get("/tickets", response_model=List[DemoTicket])
    def listing():
        return [DemoTicket.model_validate(r, from_attributes=True) for r in rows.values()]

    with TestClient(app) as c:
        yield c, other


def test_detail_response_carries_number_and_uuid(demo_api):
    client, _ = demo_api
    body = client.get(f"/tickets/{KNOWN}").json()
    assert body["id"] == str(KNOWN) and body["number"] == "TKT-3F9A1C2B"
    assert isinstance(body["number"], str)  # mobile Ticket.number is a String


def test_list_response_carries_a_number_for_every_ticket(demo_api):
    client, other = demo_api
    items = client.get("/tickets").json()
    assert {i["id"]: i["number"] for i in items} == {str(KNOWN): "TKT-3F9A1C2B", str(other): "TKT-00000000"}


def test_repeated_requests_return_the_same_number(demo_api):
    client, _ = demo_api
    assert len({client.get(f"/tickets/{KNOWN}").json()["number"] for _ in range(3)}) == 1


def test_uuid_based_addressing_is_unchanged(demo_api):
    client, _ = demo_api
    assert client.get(f"/tickets/{KNOWN}").status_code == 200
    assert client.get("/tickets/TKT-3F9A1C2B").status_code == 422  # a number is not an identifier
