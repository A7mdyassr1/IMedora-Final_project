import 'package:flutter_test/flutter_test.dart';
import 'package:imedora_mobile/core/errors/failures.dart';
import 'package:imedora_mobile/core/storage/token_storage.dart';
import 'package:imedora_mobile/core/utils/date_format.dart';
import 'package:imedora_mobile/features/auth/data/mock_auth_repository.dart';
import 'package:imedora_mobile/features/auth/presentation/auth_controller.dart';
import 'package:imedora_mobile/features/devices/data/mock_device_repository.dart';
import 'package:imedora_mobile/features/notifications/data/mock_notification_repository.dart';
import 'package:imedora_mobile/features/notifications/domain/notification.dart';
import 'package:imedora_mobile/features/notifications/presentation/notifications_controller.dart';
import 'package:imedora_mobile/features/tickets/data/mock_ticket_repository.dart';
import 'package:imedora_mobile/features/tickets/domain/ticket.dart';
import 'package:imedora_mobile/features/tickets/presentation/tickets_controller.dart'
    show LoadStatus;

const _dev1 = '22222222-2222-2222-2222-000000000001';

class _MemoryTokenStorage implements TokenStorage {
  String? token;
  @override
  Future<String?> read() async => token;
  @override
  Future<void> write(String t) async => token = t;
  @override
  Future<void> clear() async => token = null;
}

void main() {
  test('NotificationType maps to/from the notification_type string', () {
    for (final t in NotificationType.values) {
      expect(NotificationType.fromApi(t.apiValue), t);
    }
    expect(NotificationType.fromApi('something_new'), NotificationType.other);
    expect(NotificationType.fromApi(null), NotificationType.other);
  });

  test('formatRelative', () {
    final now = DateTime(2026, 10, 3, 12);
    expect(formatRelative(now.subtract(const Duration(seconds: 30)), now: now),
        'Just now');
    expect(formatRelative(now.subtract(const Duration(minutes: 5)), now: now),
        '5 min ago');
    expect(formatRelative(now.subtract(const Duration(hours: 3)), now: now),
        '3 h ago');
    expect(formatRelative(now.subtract(const Duration(days: 2)), now: now),
        '2 d ago');
    expect(formatRelative(now.subtract(const Duration(days: 10)), now: now),
        '2026-09-23');
  });

  test('mock has 5 notifications, newest first, 3 unread', () async {
    final repo = MockNotificationRepository();
    final list = await repo.getNotifications();
    expect(list.length, 5);
    expect(list.first.type, NotificationType.deviceAlert);
    expect(list.where((n) => !n.isRead).length, 3);
  });

  test('markAsRead sets read_at; unknown id throws NotFoundFailure', () async {
    final repo = MockNotificationRepository();
    await repo.markAsRead('notif-2');
    final n = (await repo.getNotifications()).firstWhere((x) => x.id == 'notif-2');
    expect(n.isRead, isTrue);
    expect(n.readAt, isNotNull);
    expect(() => repo.markAsRead('nope'), throwsA(isA<NotFoundFailure>()));
  });

  test('markAllAsRead leaves nothing unread', () async {
    final repo = MockNotificationRepository();
    await repo.markAllAsRead();
    final list = await repo.getNotifications();
    expect(list.where((n) => !n.isRead), isEmpty);
  });

  test('reporting a ticket creates a "request received" notification', () async {
    final notifs = MockNotificationRepository();
    final tickets = MockTicketRepository(
      MockDeviceRepository(),
      onTicketCreated: notifs.onTicketCreated,
    );
    final t = await tickets.createTicket(const NewTicketRequest(
      deviceId: _dev1,
      category: ProblemCategory.other,
      description: 'Something is wrong here',
    ));
    final list = await notifs.getNotifications();
    expect(list.length, 6);
    expect(list.first.type, NotificationType.ticketCreated);
    expect(list.first.relatedTicketId, t.id);
    expect(list.first.isRead, isFalse);
  });

  group('NotificationsController', () {
    late AuthController auth;
    late NotificationsController controller;

    setUp(() {
      auth = AuthController(MockAuthRepository(), _MemoryTokenStorage());
      controller = NotificationsController(MockNotificationRepository(), auth);
    });

    tearDown(() => controller.dispose());

    test('loads and counts unread', () async {
      expect(controller.status, LoadStatus.idle);
      await controller.load();
      expect(controller.status, LoadStatus.loaded);
      expect(controller.items.length, 5);
      expect(controller.unreadCount, 3);
    });

    test('markAsRead lowers the unread count immediately', () async {
      await controller.load();
      await controller.markAsRead('notif-2');
      expect(controller.unreadCount, 2);
    });

    test('markAllAsRead clears the unread count', () async {
      await controller.load();
      await controller.markAllAsRead();
      expect(controller.unreadCount, 0);
    });

    test('logging out resets the state', () async {
      await auth.login('demo', 'Demo123!');
      await controller.load();
      await auth.logout();
      expect(controller.status, LoadStatus.idle);
      expect(controller.items, isEmpty);
    });
  });
}
