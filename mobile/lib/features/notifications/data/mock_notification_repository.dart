import '../../../core/errors/failures.dart';
import '../../tickets/domain/ticket.dart';
import '../domain/notification.dart';
import '../domain/notification_repository.dart';

class MockNotificationRepository implements NotificationRepository {
  MockNotificationRepository() {
    _seed();
  }

  final List<AppNotification> _items = [];
  int _counter = 100;

  void _seed() {
    final now = DateTime.now();
    _items.addAll([
      AppNotification(
        id: 'notif-1',
        type: NotificationType.ticketResolved,
        title: 'Ticket resolved',
        body: 'TKT-1001 for Philips Ventilator was resolved: pressure sensor '
            'recalibrated and tubing replaced.',
        relatedTicketId: 'ticket-1001',
        isRead: true,
        createdAt: now.subtract(const Duration(days: 9)),
        readAt: now.subtract(const Duration(days: 8)),
      ),
      AppNotification(
        id: 'notif-2',
        type: NotificationType.ticketStatusChanged,
        title: 'Ticket in progress',
        body: 'A technician started working on TKT-1002 (CT Scanner Unit).',
        relatedTicketId: 'ticket-1002',
        createdAt: now.subtract(const Duration(days: 1)),
      ),
      AppNotification(
        id: 'notif-3',
        type: NotificationType.ticketAssigned,
        title: 'Technician assigned',
        body: 'A technician was assigned to TKT-1002 (CT Scanner Unit).',
        relatedTicketId: 'ticket-1002',
        isRead: true,
        createdAt: now.subtract(const Duration(days: 2)),
        readAt: now.subtract(const Duration(days: 2)),
      ),
      AppNotification(
        id: 'notif-4',
        type: NotificationType.ticketStatusChanged,
        title: 'Waiting for parts',
        body: 'TKT-1003 (Dialysis Machine) is waiting for a replacement '
            'power supply.',
        relatedTicketId: 'ticket-1003',
        createdAt: now.subtract(const Duration(hours: 5)),
      ),
      AppNotification(
        id: 'notif-5',
        type: NotificationType.deviceAlert,
        title: 'Important device notice',
        body: 'Dialysis Machine (DEV-003) is under maintenance. '
            'Please use an alternative device.',
        createdAt: now.subtract(const Duration(hours: 3)),
      ),
    ]);
  }

  /// Mock-only hook (wired in main.dart): the real backend creates this
  /// notification itself when a ticket is reported.
  void onTicketCreated(Ticket ticket) {
    _counter++;
    _items.insert(
      0,
      AppNotification(
        id: 'notif-$_counter',
        type: NotificationType.ticketCreated,
        title: 'Maintenance request received',
        body: '${ticket.number} for ${ticket.deviceName} was received. '
            'The biomedical team has been notified.',
        relatedTicketId: ticket.id,
        createdAt: DateTime.now(),
      ),
    );
  }

  @override
  Future<List<AppNotification>> getNotifications() async {
    await Future<void>.delayed(const Duration(milliseconds: 300));
    final sorted = [..._items]
      ..sort((a, b) => b.createdAt.compareTo(a.createdAt));
    return List.unmodifiable(sorted);
  }

  @override
  Future<void> markAsRead(String id) async {
    await Future<void>.delayed(const Duration(milliseconds: 150));
    final i = _items.indexWhere((n) => n.id == id);
    if (i == -1) throw const NotFoundFailure('Notification not found.');
    if (!_items[i].isRead) _items[i] = _items[i].markRead(DateTime.now());
  }

  @override
  Future<void> markAllAsRead() async {
    await Future<void>.delayed(const Duration(milliseconds: 150));
    final now = DateTime.now();
    for (var i = 0; i < _items.length; i++) {
      if (!_items[i].isRead) _items[i] = _items[i].markRead(now);
    }
  }
}
