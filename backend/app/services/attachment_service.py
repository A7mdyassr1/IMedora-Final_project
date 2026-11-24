"""Ticket photo attachments (B5 CP4, approved Decision 5).

Upload (POST /tickets/{id}/attachments):
- Who: the ticket's reporter, its active assignees, engineers of its hospital and admins - the
  people working on the problem. Anyone else who can see the ticket gets 403; a ticket outside the
  caller's scope is 404 (as every ticket read); a department user who has lost their department
  gets 403 department_required (no problem reporting without a department).
- When: not on deleted, closed or cancelled tickets (409); not in an inactive hospital (400).
- What: JPEG / PNG only, checked from the CONTENT; size limit MAX_UPLOAD_MB (413, refused before the
  body is read when Content-Length shows it: app/middleware/upload_limit.py); metadata such as
  GPS / EXIF is removed by re-encoding (app/utils/images.py). The original name is kept only as
  `file_name` (cleaned); the stored file gets a random key.
- At most MAX_PER_TICKET attachments per ticket, counted with the TICKET ROW LOCKED, so parallel
  uploads cannot exceed it (409 attachment_limit_reached).
- Consistency: the file is written first, then the row and its audit row are committed; if anything
  fails after the file was written, the file is deleted again. No row ever points at a missing file
  written by this code, and no file is left without a row.

Download (GET /attachments/{id}): only through the API, after the same visibility check as the
parent (ticket: ticket scope; device: device scope; maintenance record: staff record scope).
Files the backend did not store (pre-B5 rows with an external URL, missing files) are 404 - the
API never redirects to or fetches another address.

Delete (DELETE /attachments/{id}; B5 follow-up, team decision 2026-11-24):
- Only ticket photos (the only attachments the API creates); others are 400.
- Visibility first: an attachment whose ticket the caller cannot see is 404, as for downloads.
- Who: engineers of the ticket's hospital and admins may delete any photo of the ticket; the
  reporter and active assignees only the photos they uploaded themselves (403 otherwise; a
  department user without a department gets 403 department_required, as for uploads).
- When: as for uploads, not on deleted, closed or cancelled tickets (409) nor in inactive
  hospitals (400) - except for ADMINS, who may always remove a photo (e.g. one that should never
  have been uploaded, on a ticket that is already finished).
- The ticket row is locked as for uploads, so the "at most 3" count stays exact: a deleted photo
  frees its slot at once.
- Order: the row and its audit row (old values) are deleted / written and COMMITTED first; the
  file is removed only after that. If the commit fails, nothing changed (row and file remain).
  A file that is already missing, or a row whose file IMedora never stored (external URL), is
  simply removed from the database. If removing the file fails AFTER the commit (disk error), the
  deletion stands - the database is authoritative - and the now unreferenced file is logged at
  ERROR level with its storage key for manual cleanup. It can no longer be downloaded: files are
  served only through their row. This window cannot be closed without a two-phase commit between
  the database and the file system.
"""
import logging
import re
import unicodedata
import uuid
from dataclasses import dataclass
from typing import List, Optional

from sqlalchemy.orm import Session

from app.core.access import AccessScope, DeviceAccess
from app.core.config import get_settings
from app.core.exceptions import AppError, BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.core.roles import Role
from app.core.ticket_workflow import TERMINAL, TicketFacts, is_active_assignee, manages
from app.models.attachment import Attachment
from app.models.hospital import Hospital
from app.models.ticket import MaintenanceTicket
from app.repositories.attachment_repository import AttachmentRepository
from app.repositories.device_repository import DeviceRepository
from app.repositories.maintenance_repository import MaintenanceRepository
from app.repositories.ticket_repository import TicketRepository
from app.services.audit_service import AuditService
from app.storage import FileNotAvailable, Storage, get_storage
from app.utils.images import InvalidImage, sanitize

logger = logging.getLogger(__name__)

MAX_PER_TICKET = 3
STAFF_ROLES = frozenset({Role.ADMIN, Role.BIOMEDICAL_ENGINEER, Role.TECHNICIAN})


class FileTooLargeError(AppError):
    status_code = 413
    code = "file_too_large"
    default_message = "The file is too large."


class UnsupportedFileError(AppError):
    status_code = 415
    code = "unsupported_file"
    default_message = "Only JPEG and PNG images are accepted."


class AttachmentLimitError(ConflictError):
    code = "attachment_limit_reached"
    default_message = f"A ticket can have at most {MAX_PER_TICKET} attachments."


@dataclass(frozen=True)
class StoredFile:
    content: bytes
    mime_type: str
    file_name: str


def clean_file_name(name: Optional[str], extension: str) -> str:
    """The client's file name, for display only: no folders, no control characters, at most 255
    characters, and the extension of the STORED type (the content decides, not the name)."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = "".join(ch for ch in unicodedata.normalize("NFC", base) if unicodedata.category(ch)[0] != "C").strip()
    stem = base.rsplit(".", 1)[0].strip(" .") if "." in base else base.strip(" .")
    stem = stem[: 255 - len(extension)] or "photo"
    return f"{stem}{extension}"


class AttachmentService:
    def __init__(self, db: Session, storage: Optional[Storage] = None):
        self.db = db
        self.repo = AttachmentRepository(db)
        self.tickets = TicketRepository(db)
        self.audit = AuditService(db)
        self.storage = storage or get_storage()

    # ---- permissions --------------------------------------------------------------------------------
    @staticmethod
    def _facts(ticket: MaintenanceTicket) -> TicketFacts:
        return TicketFacts(ticket.hospital_id, ticket.reported_by, ticket.status,
                           frozenset(a.user_id for a in ticket.active_assignments))

    def _check_upload(self, scope: AccessScope, ticket: Optional[MaintenanceTicket]) -> MaintenanceTicket:
        if ticket is None:
            raise NotFoundError("Ticket not found.")
        # A department user without a department cannot report problems (B3.1 condition); adding
        # photos is part of reporting. Reading their own tickets stays possible (Q11).
        if scope.role is Role.DEPARTMENT_USER:
            scope.require_device_access()
        facts = self._facts(ticket)
        if not (ticket.reported_by == scope.user_id or manages(scope, facts) or is_active_assignee(scope, facts)):
            raise ForbiddenError("Only the reporter, the assigned staff, the hospital's engineers and administrators "
                                 "can add photos to this ticket.")
        if ticket.is_deleted:
            raise ConflictError("Deleted tickets cannot be modified.")
        if ticket.status in TERMINAL:
            raise ConflictError("Closed or cancelled tickets cannot receive attachments.")
        if not self.db.get(Hospital, ticket.hospital_id).is_active:
            raise BadRequestError("Hospital is inactive; attachments cannot be added to it.")
        return ticket

    # ---- upload -------------------------------------------------------------------------------------
    def upload(self, scope: AccessScope, ticket_id: uuid.UUID, file_name: Optional[str], data: bytes) -> Attachment:
        limit = get_settings().max_upload_bytes
        # cheap checks first, so nobody can make the server decode images for a ticket they cannot touch
        self._check_upload(scope, self.tickets.get(scope, ticket_id, include_deleted=scope.is_admin))
        if len(data) > limit:
            raise FileTooLargeError(f"The file is larger than {get_settings().max_upload_mb} MB.")
        try:
            image = sanitize(data)
        except InvalidImage as exc:
            raise UnsupportedFileError(str(exc)) from None

        # authoritative checks under the ticket row lock (status / count cannot change meanwhile)
        ticket = self._check_upload(scope, self.tickets.get_for_update(scope, ticket_id, include_deleted=scope.is_admin))
        if self.repo.count_for_ticket(ticket.id) >= MAX_PER_TICKET:
            raise AttachmentLimitError()

        key = self.storage.save(image.content, image.extension)
        try:
            attachment = self.repo.add(Attachment(
                organization_id=ticket.organization_id, hospital_id=ticket.hospital_id, ticket_id=ticket.id,
                uploaded_by=scope.user_id, file_url=f"{self.storage.scheme}:{key}",
                file_name=clean_file_name(file_name, image.extension), mime_type=image.mime_type,
                file_size_bytes=len(image.content),
            ))
            self.audit.inserted(scope.user_id, attachment)
            self.db.commit()
        except BaseException:
            self.db.rollback()
            self.storage.delete(key)  # Decision 5: no file without its row
            raise
        logger.info("Attachment stored id=%s ticket=%s bytes=%s type=%s", attachment.id, ticket.id,
                    len(image.content), image.mime_type)
        return self.repo.get(scope.organization_id, attachment.id)

    # ---- reads --------------------------------------------------------------------------------------
    def for_ticket(self, scope: AccessScope, ticket_id: uuid.UUID) -> List[Attachment]:
        if self.tickets.get(scope, ticket_id, include_deleted=scope.is_admin) is None:
            raise NotFoundError("Ticket not found.")
        return self.repo.for_ticket(ticket_id)

    def ticket_attachments(self, ticket: MaintenanceTicket) -> List[Attachment]:
        """For a ticket the caller has already been allowed to read."""
        return self.repo.for_ticket(ticket.id)

    def _visible(self, scope: AccessScope, a: Attachment) -> bool:
        if a.ticket_id is not None:
            return self.tickets.get(scope, a.ticket_id, include_deleted=scope.is_admin) is not None
        if a.maintenance_record_id is not None:
            return scope.role in STAFF_ROLES and MaintenanceRepository(self.db).get_record(
                scope, a.maintenance_record_id) is not None
        if a.device_id is not None:
            return scope.device_access is not DeviceAccess.NONE and DeviceRepository(self.db).get(scope, a.device_id) is not None
        return False

    # ---- delete -------------------------------------------------------------------------------------
    def _check_delete(self, scope: AccessScope, a: Attachment, ticket: Optional[MaintenanceTicket]) -> None:
        if ticket is None:
            raise NotFoundError("Attachment not found.")
        if scope.is_admin:
            return  # admins may always remove a photo (privacy), whatever the ticket's state
        if scope.role is Role.DEPARTMENT_USER:
            scope.require_device_access()
        facts = self._facts(ticket)
        works_on_it = ticket.reported_by == scope.user_id or is_active_assignee(scope, facts)
        if not (manages(scope, facts) or (works_on_it and a.uploaded_by == scope.user_id)):
            raise ForbiddenError("Only the person who added this photo, the hospital's engineers and administrators "
                                 "can delete it.")
        if ticket.is_deleted:
            raise ConflictError("Deleted tickets cannot be modified.")
        if ticket.status in TERMINAL:
            raise ConflictError("Photos of closed or cancelled tickets can only be removed by an administrator.")
        if not self.db.get(Hospital, ticket.hospital_id).is_active:
            raise BadRequestError("Hospital is inactive; its attachments cannot be changed.")

    def delete(self, scope: AccessScope, attachment_id: uuid.UUID) -> None:
        a = self.repo.get(scope.organization_id, attachment_id)
        if a is None or not self._visible(scope, a):
            raise NotFoundError("Attachment not found.")
        if a.ticket_id is None:
            raise BadRequestError("Only ticket photos can be deleted.")
        # lock order as for uploads: ticket row first (keeps the per-ticket count exact), then the row
        ticket = self.tickets.get_for_update(scope, a.ticket_id, include_deleted=scope.is_admin)
        self._check_delete(scope, a, ticket)
        a = self.repo.get_for_update(scope.organization_id, attachment_id)
        if a is None:  # deleted by someone else while we waited for the lock
            raise NotFoundError("Attachment not found.")
        scheme, _, key = (a.file_url or "").partition(":")
        ticket_id = a.ticket_id
        try:
            self.audit.deleted(scope.user_id, a)
            self.repo.delete(a)
            self.db.commit()
        except BaseException:
            self.db.rollback()  # nothing changed: the row and its file both remain
            raise
        logger.info("Attachment deleted id=%s ticket=%s by=%s", attachment_id, ticket_id, scope.user_id)
        if scheme != self.storage.scheme:
            return  # IMedora never stored this file (pre-B5 external URL): nothing to remove
        try:
            self.storage.delete(key)  # a file that is already missing is not an error
        except Exception:
            logger.error("Attachment row deleted but its file could not be removed: orphaned storage key %s "
                         "(attachment %s); remove it manually", key, attachment_id, exc_info=True)

    def download(self, scope: AccessScope, attachment_id: uuid.UUID) -> StoredFile:
        a = self.repo.get(scope.organization_id, attachment_id)
        if a is None or not self._visible(scope, a):
            raise NotFoundError("Attachment not found.")
        scheme, _, key = (a.file_url or "").partition(":")
        if scheme != self.storage.scheme:
            raise NotFoundError("The file of this attachment is not stored by IMedora.")
        try:
            content = self.storage.open(key)
        except FileNotAvailable:
            logger.warning("Attachment file missing id=%s", a.id)
            raise NotFoundError("The file of this attachment is not available.") from None
        return StoredFile(content=content, mime_type=a.mime_type or "application/octet-stream",
                          file_name=a.file_name or "attachment")
