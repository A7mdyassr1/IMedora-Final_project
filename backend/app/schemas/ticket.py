"""Reusable pieces for maintenance-ticket API schemas (B3.1 CP2).

There are no ticket endpoints yet: they arrive in B4. B4's ticket response schemas inherit
`TicketNumberMixin`, which adds a read-only `number` field computed from `id`:

    class TicketResponse(TicketNumberMixin):
        id: uuid.UUID            # still the identifier used by every API call
        status: TicketStatus
        ...

    TicketResponse.model_validate(ticket_orm_row, from_attributes=True)
    # -> {"id": "3f9a1c2b-...", "number": "TKT-3F9A1C2B", "status": ...}

`number` is computed on serialization only: it cannot be sent by a client, is not stored,
and needs no database column or query.
"""
import uuid

from pydantic import BaseModel, computed_field

from app.utils.ticket_number import ticket_number


class TicketNumberMixin(BaseModel):
    id: uuid.UUID

    @computed_field(
        description="Short human-readable ticket number derived from the UUID, e.g. TKT-3F9A1C2B. "
                    "Display only; use `id` to address the ticket.",
        examples=["TKT-3F9A1C2B"],
    )
    @property
    def number(self) -> str:
        return ticket_number(self.id)
