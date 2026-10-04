// Mirrors the IMedora `notifications` table.
//
// DB NOTES: `notification_type` is a free varchar(50), not an enum, so the
// mobile app maps known strings and falls back to `other` for new ones.
// The DB also guarantees: is_read = true  =>  read_at IS NOT NULL.

enum NotificationType {
  ticketCreated('ticket_created'),
  ticketAssigned('ticket_assigned'),
  ticketStatusChanged('ticket_status_changed'),
  ticketResolved('ticket_resolved'),
  deviceAlert('device_alert'),
  other('other');

  const NotificationType(this.apiValue);

  /// Value stored in notifications.notification_type.
  final String apiValue;

  static NotificationType fromApi(String? value) {
    for (final t in values) {
      if (t.apiValue == value) return t;
    }
    return NotificationType.other;
  }
}

/// Named AppNotification to avoid clashing with Flutter's own Notification.
class AppNotification {
  const AppNotification({
    required this.id,
    required this.type,
    required this.title,
    required this.createdAt,
    this.body,
    this.relatedTicketId,
    this.isRead = false,
    this.readAt,
  });

  final String id;
  final NotificationType type;
  final String title;
  final String? body;
  final String? relatedTicketId;
  final bool isRead;
  final DateTime createdAt;
  final DateTime? readAt;

  AppNotification markRead(DateTime at) => AppNotification(
        id: id,
        type: type,
        title: title,
        body: body,
        relatedTicketId: relatedTicketId,
        isRead: true,
        createdAt: createdAt,
        readAt: at,
      );
}
