"""In-app notifications (B5 CP3; deferred from B4 by decision Q2).

Delivery: in-app only - rows in `notifications`, read by the mobile app through
GET /notifications, PATCH /notifications/{id}/read and POST /notifications/read-all (the contract
in mobile/lib/features/notifications). No push or e-mail channel exists in the project yet.

Producers (`Notifier`) are called by the services that make the business change, INSIDE their
transaction and before their commit: a notification exists if and only if its event was saved,
and both are audited together. Only the five types the mobile app knows are produced:

    type                   event                                        recipients
    ---------------------  -------------------------------------------  ------------------------------------------
    ticket_created         POST /tickets                                the reporter ("request received") and the
                                                                        hospital's biomedical team - engineers and
                                                                        technicians, who assign / take tickets (Q5)
    ticket_assigned        an assignment (incl. a technician taking     the assignee, and the reporter
                           the ticket)
    ticket_status_changed  in_progress, waiting_for_parts, closed,      the reporter and the active assignees
                           cancelled, reopened, back to open when the
                           last assignee is removed
    ticket_resolved        resolved                                     the reporter (with the work done, Q9)
    device_alert           a device's status changes between active,    the device's department users (the people
                           under_maintenance and out_of_service         who use it)

B8 adds one type for administrators (the mobile app shows unknown types as `other`):
    password_reset_requested  POST /auth/forgot-password for an account  the organization's admins, except the
                              that can sign in (no e-mail service)       account itself and admins who still have
                                                                         an unread request for that account

Rules:
- Nobody is notified about their own action (a reporter who cancels, a technician who takes a
  ticket); the reporter's "request received" confirmation is the one exception, as in the mobile app.
- Only users who can sign in (active, not deleted) receive notifications; recipients are de-duplicated.
- Texts never contain staff names: department users see staff as roles (Q9). They contain the
  ticket number, the device and, for resolutions, the work description the reporter may see (Q9).
- Each notification, and each change of its read state, writes an audit row in the same transaction.
- Reading: every role reads ONLY its own notifications; another user's id is 404.
"""
import logging
import uuid
from typing import Iterable, List, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.access import AccessScope
from app.core.enums import AuditAction, DeviceStatus, TicketStatus
from app.core.exceptions import NotFoundError
from app.core.roles import Role
from app.models.device import Device
from app.models.notification import Notification
from app.models.ticket import MaintenanceTicket
from app.repositories.maintenance_repository import MaintenanceRepository
from app.repositories.notification_repository import NotificationRepository
from app.services.audit_service import AuditService, snapshot
from app.utils.ticket_number import ticket_number

logger = logging.getLogger(__name__)

TICKET_CREATED = "ticket_created"
TICKET_ASSIGNED = "ticket_assigned"
TICKET_STATUS_CHANGED = "ticket_status_changed"
TICKET_RESOLVED = "ticket_resolved"
DEVICE_ALERT = "device_alert"
PASSWORD_RESET_REQUESTED = "password_reset_requested"
TYPES = (TICKET_CREATED, TICKET_ASSIGNED, TICKET_STATUS_CHANGED, TICKET_RESOLVED, DEVICE_ALERT)

BIOMEDICAL_TEAM = (Role.BIOMEDICAL_ENGINEER.value, Role.TECHNICIAN.value)
WORK_SUMMARY_MAX = 300
ALERT_STATUSES = frozenset({DeviceStatus.ACTIVE, DeviceStatus.UNDER_MAINTENANCE, DeviceStatus.OUT_OF_SERVICE})

_ROLE_TEXT = {Role.TECHNICIAN.value: "A technician", Role.BIOMEDICAL_ENGINEER.value: "A biomedical engineer",
              Role.ADMIN.value: "An administrator"}

# (title, body template) per status set by hand; {t} = ticket label "TKT-… (device)"
_STATUS_TEXT = {
    TicketStatus.IN_PROGRESS: ("Ticket in progress", "Work has started on {t}."),
    TicketStatus.WAITING_FOR_PARTS: ("Waiting for parts", "{t} is waiting for spare parts."),
    TicketStatus.CLOSED: ("Ticket closed", "{t} was closed."),
    TicketStatus.CANCELLED: ("Ticket cancelled", "{t} was cancelled."),
    TicketStatus.OPEN: ("Waiting for a technician", "{t} is waiting for a technician again."),
}


def _device_label(device: Device) -> str:
    return f"{device.name} ({device.device_code})"


def _ticket_label(ticket: MaintenanceTicket) -> str:
    return f"{ticket_number(ticket.id)} ({_device_label(ticket.device)})"


def _shorten(text: str, limit: int = WORK_SUMMARY_MAX) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


class Notifier:
    """Creates notifications in the CALLER's transaction (no commit)."""

    def __init__(self, db: Session, audit: AuditService):
        self.db = db
        self.repo = NotificationRepository(db)
        self.audit = audit

    def _send(self, actor_id: Optional[uuid.UUID], organization_id: uuid.UUID, recipients: Iterable[uuid.UUID],
              kind: str, title: str, body: str, ticket_id: Optional[uuid.UUID] = None,
              notify_actor: bool = False) -> List[Notification]:
        wanted = {r for r in recipients if r is not None and (notify_actor or r != actor_id)}
        users = sorted(self.repo.reachable(organization_id, wanted), key=str)
        rows = [Notification(organization_id=organization_id, user_id=u, related_ticket_id=ticket_id,
                             title=title, body=body, notification_type=kind) for u in users]
        if rows:
            self.repo.add_all(rows)
            for row in rows:
                self.audit.inserted(actor_id, row)
            logger.info("Notifications type=%s ticket=%s recipients=%s", kind, ticket_id, len(rows))
        return rows

    # ---- accounts (B8) ----------------------------------------------------------------------------------
    def password_reset_requested(self, user) -> int:
        """Somebody asked for `user`'s password to be reset (the request is not signed in: no actor).
        Returns the number of admins notified. The texts name the account: only admins receive them."""
        title = "Password reset requested"
        body = (f"{user.full_name} ({user.email}) cannot sign in and asked for a password reset. "
                "Set a new password in user management.")
        admins = self.repo.organization_admins(user.organization_id)
        waiting = self.repo.unread_of(PASSWORD_RESET_REQUESTED, body, admins)
        return len(self._send(None, user.organization_id, [a for a in admins if a != user.id and a not in waiting],
                              PASSWORD_RESET_REQUESTED, title, body))

    # ---- tickets ----------------------------------------------------------------------------------------
    def ticket_created(self, actor_id: uuid.UUID, ticket: MaintenanceTicket) -> None:
        label = _ticket_label(ticket)
        self._send(actor_id, ticket.organization_id, [ticket.reported_by], TICKET_CREATED,
                   "Maintenance request received",
                   f"{label} was received. The biomedical team has been notified.",
                   ticket.id, notify_actor=True)
        team = self.repo.hospital_staff(ticket.organization_id, ticket.hospital_id, BIOMEDICAL_TEAM)
        self._send(actor_id, ticket.organization_id, [u for u in team if u != ticket.reported_by], TICKET_CREATED,
                   "New maintenance request",
                   f"{label}, {ticket.device.department.name}: {ticket.priority.value} priority.", ticket.id)

    def ticket_assigned(self, actor_id: uuid.UUID, ticket: MaintenanceTicket, assignee_id: uuid.UUID,
                        assignee_role: str) -> None:
        label = _ticket_label(ticket)
        self._send(actor_id, ticket.organization_id, [assignee_id], TICKET_ASSIGNED, "Ticket assigned to you",
                   f"You were assigned {label}.", ticket.id)
        if ticket.reported_by != assignee_id:
            who = _ROLE_TEXT.get(assignee_role, "A staff member")
            self._send(actor_id, ticket.organization_id, [ticket.reported_by], TICKET_ASSIGNED,
                       "Technician assigned", f"{who} was assigned to {label}.", ticket.id)

    def ticket_status_changed(self, actor_id: uuid.UUID, ticket: MaintenanceTicket, old: TicketStatus,
                              new: TicketStatus) -> None:
        label = _ticket_label(ticket)
        if new is TicketStatus.RESOLVED:
            work = MaintenanceRepository(self.db).work_for_ticket(ticket.id, ticket.device_id)
            done = f": {_shorten(work[-1][2])}" if work else "."
            self._send(actor_id, ticket.organization_id, [ticket.reported_by], TICKET_RESOLVED, "Ticket resolved",
                       f"{label} was resolved{done}", ticket.id)
            return
        if old is TicketStatus.RESOLVED and new is TicketStatus.IN_PROGRESS:
            title, body = "Ticket reopened", f"{label} was reopened."
        elif new in _STATUS_TEXT:
            title, template = _STATUS_TEXT[new]
            body = template.format(t=label)
        else:  # assigned: announced by ticket_assigned
            return
        recipients = [ticket.reported_by, *(a.user_id for a in ticket.active_assignments)]
        self._send(actor_id, ticket.organization_id, recipients, TICKET_STATUS_CHANGED, title, body, ticket.id)

    # ---- devices ----------------------------------------------------------------------------------------
    def device_status_changed(self, actor_id: uuid.UUID, device: Device, old: DeviceStatus, new: DeviceStatus) -> None:
        if old == new or old not in ALERT_STATUSES or new not in ALERT_STATUSES:
            return
        label = _device_label(device)
        if new is DeviceStatus.ACTIVE:
            title, body = "Device back in service", f"{label} is available again."
        else:
            state = "under maintenance" if new is DeviceStatus.UNDER_MAINTENANCE else "out of service"
            title, body = "Important device notice", f"{label} is {state}. Please use an alternative device."
        users = self.repo.department_users(device.organization_id, device.department_id, Role.DEPARTMENT_USER.value)
        self._send(actor_id, device.organization_id, users, DEVICE_ALERT, title, body)


class NotificationService:
    """The caller's own inbox."""

    def __init__(self, db: Session):
        self.db = db
        self.repo = NotificationRepository(db)
        self.audit = AuditService(db)

    def list(self, scope: AccessScope, unread_only: bool, page: int, page_size: int) -> Tuple[List[Notification], int, int]:
        items, total = self.repo.list_own(scope.user_id, scope.organization_id, unread_only, page, page_size)
        return items, total, self.repo.unread_count(scope.user_id, scope.organization_id)

    def mark_read(self, scope: AccessScope, notification_id: uuid.UUID) -> Notification:
        n = self.repo.get_own(scope.user_id, scope.organization_id, notification_id, for_update=True)
        if n is None:
            raise NotFoundError("Notification not found.")
        if n.is_read:  # idempotent
            self.db.rollback()
            return self.repo.get_own(scope.user_id, scope.organization_id, notification_id)
        before = snapshot(n)
        n.is_read = True
        n.read_at = func.now()  # database clock: CHECK read_at >= created_at
        self.db.flush()
        self.db.refresh(n)
        self.audit.updated(scope.user_id, n, before)
        self.db.commit()
        return self.repo.get_own(scope.user_id, scope.organization_id, notification_id)

    def mark_all_read(self, scope: AccessScope) -> int:
        marked = self.repo.mark_all_read(scope.user_id, scope.organization_id)
        for notification_id, read_at in marked:
            self.audit.record(actor_id=scope.user_id, organization_id=scope.organization_id,
                              table_name=Notification.__tablename__, record_id=notification_id,
                              action=AuditAction.UPDATE, old_values={"is_read": False, "read_at": None},
                              new_values={"is_read": True, "read_at": read_at.isoformat()})
        self.db.commit()
        return len(marked)
