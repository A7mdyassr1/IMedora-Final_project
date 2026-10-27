"""Device tools: look devices up, or list them by status/risk/category/department/location."""
from ai.services.data.base import DataProvider
from ai.tools.base import many, single, tool


@tool("device")
def search_devices(provider: DataProvider, query: str, limit: int = 20) -> dict:
    """Search devices by code, name, or category text."""
    return many(provider.search_devices(query, limit), "devices")


@tool("device")
def get_device(provider: DataProvider, device_id: str) -> dict:
    """Get one device by its id."""
    return single(provider.get_device(device_id), "device")


@tool("device")
def get_device_profile(provider: DataProvider, device_id: str) -> dict:
    """Get the full profile of one device (manufacturer, model, location, risk, dates)."""
    return single(provider.get_device_profile(device_id), "device profile")


@tool("device")
def get_devices_by_status(provider: DataProvider, status: str) -> dict:
    """List devices with a given status: active, under_maintenance, out_of_service, decommissioned."""
    return many(provider.get_devices_by_status(status), f"devices with status '{status}'")


@tool("device")
def get_devices_by_risk(provider: DataProvider, risk_level: str) -> dict:
    """List devices whose CURRENT risk level is low, medium, high, or critical."""
    return many(provider.get_devices_by_risk(risk_level), f"devices with current risk '{risk_level}'")


@tool("device")
def get_devices_by_category(provider: DataProvider, category: str) -> dict:
    """List devices of a category, e.g. Ventilator or CT Scanner."""
    return many(provider.get_devices_by_category(category), f"devices in category '{category}'")


@tool("device")
def get_devices_by_department(provider: DataProvider, department: str) -> dict:
    """List devices in a department, e.g. ICU or Radiology."""
    return many(provider.get_devices_by_department(department), f"devices in department '{department}'")


@tool("device")
def get_devices_by_location(provider: DataProvider, location: str) -> dict:
    """List devices whose location contains the given text (building, floor, or room)."""
    return many(provider.get_devices_by_location(location), f"devices at location '{location}'")


TOOLS = [
    search_devices, get_device, get_device_profile, get_devices_by_status,
    get_devices_by_risk, get_devices_by_category, get_devices_by_department, get_devices_by_location,
]
