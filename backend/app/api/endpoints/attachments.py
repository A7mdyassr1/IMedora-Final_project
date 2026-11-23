"""Attachment downloads (B5 CP4, Decision 5): files are private and leave the server only here,
after authentication and the same visibility check as their ticket / device / record."""
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
