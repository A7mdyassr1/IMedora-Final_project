"""Shared B5 parts scenario on top of `tickets` (tests only): catalog parts and stock rows created
through the API. Cleanup is done by `tickets` (tests/ticket_scene.py): usage with its records, then
the organizations' stock rows, then the parts whose part number contains the test's suffix."""
import pytest

from tests.world import API


@pytest.fixture
def stock(tickets, client):
    world, h = tickets["world"], tickets["h"]

    def part(label="Power Supply Unit", number=None, unit="piece", headers=None):
        number = number or f"PN-{label.split()[0][:6].upper()}-{world['sfx']}"
        r = client.post(f"{API}/parts", headers=headers or h["admin"],
                        json={"name": f"{label}", "part_number": number, "unit": unit})
        assert r.status_code == 201, r.text
        return r.json()

    def stock_row(part_id, hospital_key="h1", quantity=10, threshold=None, headers=None):
        r = client.post(f"{API}/inventory", headers=headers or h["admin"],
                        json={"part_id": part_id, "hospital_id": world[hospital_key], "quantity_on_hand": quantity,
                              "reorder_threshold": threshold, "reason": "opening stock"})
        assert r.status_code == 201, r.text
        return r.json()

    def quantity(inventory_id):
        return tickets["sql"]("SELECT quantity_on_hand FROM part_inventory WHERE id = :i", i=inventory_id)[0][0]

    yield dict(tickets, part=part, stock_row=stock_row, quantity=quantity)
