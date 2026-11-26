"""How a person appears in API responses (decision Q9), shared by ticket and device-history responses.

Staff (technicians, engineers, admins) see names. A department user sees other staff as a role
description only (`id` null, `name` e.g. "Technician") and always sees themselves by name.

B6-L4: this lived in `app/schemas/ticket.py` as the private helper `_person`, which device history
imported. It is the one shared rule for both features, so it has its own small public module; the
JSON representation is unchanged (same model name `PersonRef`, same fields, same values).
"""
import uuid
from typing import TYPE_CHECKING, Optional

from pydantic import BaseModel

from app.services.ticket_timeline import Person, person_display

if TYPE_CHECKING:  # pragma: no cover
    from app.core.access import AccessScope


class PersonRef(BaseModel):
    """A person as the viewer may see them. For department users, staff appear as a role
    description only: `id` is null and `name` is e.g. "Technician" (decision Q9)."""
    id: Optional[uuid.UUID] = None
    name: str
    role: str


def person_ref(user, scope: "AccessScope") -> PersonRef:
    """`user` (an ORM User with its role) as `scope`'s caller may see them."""
    p = Person(user.id, user.full_name, user.role.name)
    visible = scope.sees_staff_names or user.id == scope.user_id
    return PersonRef(id=user.id if visible else None, name=person_display(p, scope.user_id, scope.sees_staff_names),
                     role=p.role)
