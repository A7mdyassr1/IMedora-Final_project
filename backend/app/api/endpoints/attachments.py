"""Attachment downloads (B5 CP4, Decision 5) and deletion (B5 follow-up): files are private and leave
the server only here, after authentication and the same visibility check as their ticket / device /
record."""
import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser
from app.core.access import scope_for
from app.core.database import get_db
from app.models.user import User
from app.services.attachment_service import AttachmentService

router = APIRouter(tags=["attachments"])


@router.get(
    "/attachments/{attachment_id}", summary="Download an attachment",
    response_class=Response, responses={200: {"content": {"image/jpeg": {}, "image/png": {}}}},
    description="404 when the attachment is not visible to the caller, or when its file is not stored by IMedora.",
)
def download_attachment(attachment_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    f = AttachmentService(db).download(scope_for(user), attachment_id)
    return Response(content=f.content, media_type=f.mime_type, headers={
        "Content-Disposition": f"inline; filename*=UTF-8''{quote(f.file_name)}",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    })


@router.delete(
    "/attachments/{attachment_id}", status_code=204, summary="Delete a ticket photo",
    description=(
        "Engineers of the ticket's hospital and administrators: any photo of the ticket; the reporter and "
        "active assignees: only the photos they added. Not on closed, cancelled or deleted tickets (409) nor "
        "in inactive hospitals (400), except for administrators. Removes the record and the stored file, "
        "is audited, and frees the photo's slot in the limit of 3 per ticket. 404 when the attachment is "
        "not visible to the caller."
    ),
)
def delete_attachment(attachment_id: uuid.UUID, user: User = CurrentUser, db: Session = Depends(get_db)):
    AttachmentService(db).delete(scope_for(user), attachment_id)
    return Response(status_code=204)
