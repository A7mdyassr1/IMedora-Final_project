"""Human-readable maintenance-ticket numbers (B3.1 CP2, team decision: Option A).

    TKT-{first 8 hexadecimal characters of the ticket's UUID, upper-case}
    e.g. id 3f9a1c2b-7d4e-4a1b-9c3d-2e5f6a7b8c9d  ->  TKT-3F9A1C2B

- Derived on the fly from maintenance_tickets.id: nothing is stored, no column, no sequence,
  no migration, no database access. The same ticket therefore always has the same number.
- Display only. The UUID stays the ticket's identifier for every API call and foreign key.
- Not guaranteed unique: 8 hex characters = 32 bits, so two tickets can share a number
  (unlikely below tens of thousands of tickets). Never look a ticket up by its number alone.
"""
import re
import uuid
from typing import Union

PREFIX = "TKT-"
HEX_CHARS = 8
TICKET_NUMBER_PATTERN = re.compile(r"^TKT-[0-9A-F]{8}$")


def ticket_number(ticket_id: Union[uuid.UUID, str]) -> str:
    """The display number for a ticket UUID (a UUID object or its string form)."""
    value = ticket_id if isinstance(ticket_id, uuid.UUID) else uuid.UUID(str(ticket_id))
    return PREFIX + value.hex[:HEX_CHARS].upper()
