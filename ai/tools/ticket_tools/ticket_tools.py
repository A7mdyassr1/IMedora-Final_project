"""Ticket tools: search, lookup, open/resolved lists, statistics."""
from typing import Optional

from ai.services.data.base import DataProvider
from ai.tools.base import many, single, stats, tool, to_date


@tool("ticket")
def search_tickets(provider: DataProvider, query: str, limit: int = 20) -> dict:
    """Search tickets by problem description text."""
    return many(provider.search_tickets(query, limit), "tickets")


@tool("ticket")
def get_ticket(provider: DataProvider, ticket_id: str) -> dict:
    """Get one ticket by its id."""
    return single(provider.get_ticket(ticket_id), "ticket")


@tool("ticket")
def get_device_tickets(provider: DataProvider, device_id: str) -> dict:
    """All tickets ever raised for a device."""
    return many(provider.get_device_tickets(device_id), "tickets for this device")


@tool("ticket")
def get_open_tickets(provider: DataProvider, hospital_id: Optional[str] = None, department: Optional[str] = None) -> dict:
    """Tickets not yet resolved (open, assigned, in progress, waiting for parts). Optional hospital/department filter."""
    return many(provider.get_open_tickets(hospital_id, department), "open tickets")


@tool("ticket")
def get_resolved_tickets(provider: DataProvider, hospital_id: Optional[str] = None, date_from: Optional[str] = None) -> dict:
    """Resolved or closed tickets. Optional hospital filter and 'resolved since' date."""
    return many(provider.get_resolved_tickets(hospital_id, to_date(date_from)), "resolved tickets")


@tool("ticket")
def get_ticket_statistics(
    provider: DataProvider, priority: Optional[str] = None, status: Optional[str] = None,
    department: Optional[str] = None, date_from: Optional[str] = None, date_to: Optional[str] = None,
) -> dict:
    """Ticket counts overall and by status, filterable by priority, status, department, created-date range."""
    values = provider.get_ticket_statistics(priority, status, department, to_date(date_from), to_date(date_to))
    return stats(values, priority=priority, status=status, department=department, date_from=date_from, date_to=date_to)


TOOLS = [search_tickets, get_ticket, get_device_tickets, get_open_tickets, get_resolved_tickets, get_ticket_statistics]
