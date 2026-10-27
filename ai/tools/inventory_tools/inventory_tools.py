"""
Inventory tools.

Per the brief: the AI must never claim a part is in stock unless the
provider confirms it. So `get_part_inventory` returns an explicit
`in_stock` flag computed from the provider's rows - an empty result
means "no inventory record", which is reported as exactly that, never
as "out of stock" or "in stock".
"""
from typing import Optional

from ai.services.data.base import DataProvider
from ai.tools.base import many, stats, tool, to_date


@tool("inventory")
def get_part_inventory(provider: DataProvider, hospital_id: str, part_name: Optional[str] = None) -> dict:
    """Stock levels at a hospital, optionally filtered by part name text."""
    rows = provider.get_part_inventory(hospital_id, part_name)
    result = many(rows, "inventory records")
    result["in_stock"] = any(r.quantity_on_hand > 0 for r in rows)
    return result


@tool("inventory")
def get_low_stock_parts(provider: DataProvider, hospital_id: str) -> dict:
    """Parts at or below their reorder threshold at a hospital."""
    return many(provider.get_low_stock_parts(hospital_id), "low-stock parts")


@tool("inventory")
def get_part_usage(provider: DataProvider, part_id: str, date_from: Optional[str] = None) -> dict:
    """Maintenance events that consumed a given part."""
    return many(provider.get_part_usage(part_id, to_date(date_from)), "usage records for this part")


@tool("inventory")
def get_inventory_statistics(provider: DataProvider, hospital_id: str) -> dict:
    """Inventory summary of a hospital: parts tracked, low-stock count, total units on hand."""
    return stats(provider.get_inventory_statistics(hospital_id), hospital_id=hospital_id)


TOOLS = [get_part_inventory, get_low_stock_parts, get_part_usage, get_inventory_statistics]
