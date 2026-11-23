"""B5 CP1/CP2 unit tests (no database): stock error mapping, request validation, low-stock rule."""
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError, InternalError

from app.core.db_errors import CONSTRAINT_MESSAGES, describe_integrity_error, describe_trigger_error
from app.models.part import PartInventory
from app.schemas.part import InventoryAdjustment, PartCreate, PartUpdate, PartUse


def _orig(pgcode, constraint=None, context=None):
    return SimpleNamespace(pgcode=pgcode, diag=SimpleNamespace(constraint_name=constraint, context=context))


def test_negative_stock_is_a_conflict_not_a_validation_error():
    exc = IntegrityError("UPDATE part_inventory ...", {}, _orig("23514", "ck_inventory_quantity_non_negative"))
    assert describe_integrity_error(exc)[:2] == (409, "insufficient_stock")
    other = IntegrityError("...", {}, _orig("23514", "ck_maintenance_parts_quantity_positive"))
    assert describe_integrity_error(other)[:2] == (422, "constraint_violation")


@pytest.mark.parametrize("constraint, status, code", [
    ("parts_part_number_key", 409, "conflict"),
    ("uq_inventory_hospital_part", 409, "conflict"),
    ("uq_record_part", 409, "conflict"),
    ("part_inventory_part_id_fkey", 409, "in_use"),
    ("maintenance_parts_part_id_fkey", 409, "in_use"),
])
def test_b5_constraint_names_have_clear_messages(constraint, status, code):
    pgcode = "23503" if constraint.endswith("_fkey") else "23505"
    s, c, message = describe_integrity_error(IntegrityError("...", {}, _orig(pgcode, constraint)))
    assert (s, c, message) == (status, code, CONSTRAINT_MESSAGES[constraint])


def test_trigger_errors_are_mapped_without_leaking_the_trigger_text():
    stocked = InternalError("INSERT ...", {}, _orig("P0001", context="PL/pgSQL function adjust_part_inventory_on_usage() line 12"))
    assert describe_trigger_error(stocked) == (
        409, "part_not_stocked", "This part is not stocked at the device's hospital, so its use cannot be recorded.")
    unknown = InternalError("...", {}, _orig("P0001", context="PL/pgSQL function something_else()"))
    assert describe_trigger_error(unknown)[:2] == (409, "conflict")
    assert describe_trigger_error(InternalError("...", {}, _orig("XX000"))) is None


def test_trigger_error_handler_returns_409_and_hides_sql(app):
    @app.get("/__t/trigger")
    def _boom():
        raise InternalError("INSERT INTO maintenance_parts ... secret sql", {},
                            _orig("P0001", context="PL/pgSQL function adjust_part_inventory_on_usage() line 12"))

    from fastapi.testclient import TestClient
    r = TestClient(app).get("/__t/trigger")
    assert r.status_code == 409 and r.json()["error"]["code"] == "part_not_stocked"
    assert "secret" not in r.text and "maintenance_parts" not in r.text


def test_adjustment_rules():
    assert InventoryAdjustment(kind="restock", quantity_change=5, reason=" PO-1 ").reason == "PO-1"
    assert InventoryAdjustment(kind="correction", quantity_change=-5, reason="count").quantity_change == -5
    for bad in (dict(kind="restock", quantity_change=-1, reason="x"), dict(kind="correction", quantity_change=0, reason="x"),
                dict(kind="correction", quantity_change=1, reason=""), dict(kind="transfer", quantity_change=1, reason="x"),
                dict(kind="restock", quantity_change=100_001, reason="x"),
                dict(kind="restock", quantity_change=1, reason="x", quantity_on_hand=3)):
        with pytest.raises(ValidationError):
            InventoryAdjustment(**bad)


def test_part_validation():
    p = PartCreate(name=" Tubing ", part_number=" pn-tube-1 ", unit=" Meter ")
    assert (p.name, p.part_number, p.unit) == ("Tubing", "PN-TUBE-1", "meter")
    for bad in (dict(name="x", part_number="PN 1"), dict(name="", part_number="PN-1"), dict(name="x", part_number="")):
        with pytest.raises(ValidationError):
            PartCreate(**bad)
    with pytest.raises(ValidationError):
        PartUpdate()
    with pytest.raises(ValidationError):
        PartUpdate(unit=None)
    assert PartUpdate(description=None).model_fields_set == {"description"}
    with pytest.raises(ValidationError):
        PartUse(part_id="5f0c2b1e-0000-4000-8000-000000000000", quantity=0)


@pytest.mark.parametrize("on_hand, threshold, low", [(5, None, False), (5, 4, False), (4, 4, True), (0, 0, True)])
def test_low_stock_rule(on_hand, threshold, low):
    assert PartInventory(quantity_on_hand=on_hand, reorder_threshold=threshold).is_low_stock is low
