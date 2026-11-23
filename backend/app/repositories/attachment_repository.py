"""Attachments (B5 CP4). Visibility is decided by the PARENT (ticket, device or record) in the
service: this repository only loads rows by id or by ticket."""
import uuid
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.attachment import Attachment


class AttachmentRepository:
    def __init__(self, db: Session):
        self.db = db

    def add(self, obj: Attachment) -> Attachment:
        self.db.add(obj)
        self.db.flush()
        return obj

    def get(self, organization_id: uuid.UUID, attachment_id: uuid.UUID) -> Optional[Attachment]:
        return self.db.scalar(select(Attachment).where(Attachment.id == attachment_id,
                                                       Attachment.organization_id == organization_id))

    def for_ticket(self, ticket_id: uuid.UUID) -> List[Attachment]:
        return list(self.db.scalars(select(Attachment).where(Attachment.ticket_id == ticket_id)
                                    .order_by(Attachment.created_at, Attachment.id)))

    def count_for_ticket(self, ticket_id: uuid.UUID) -> int:
        return self.db.scalar(select(func.count()).select_from(Attachment).where(Attachment.ticket_id == ticket_id)) or 0
