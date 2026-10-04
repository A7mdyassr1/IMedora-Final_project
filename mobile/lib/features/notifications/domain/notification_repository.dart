import 'notification.dart';

/// UI depends on this interface only.
/// Mock now -> ApiNotificationRepository (GET /notifications,
/// PATCH /notifications/{id}/read, POST /notifications/read-all) later.
abstract class NotificationRepository {
  /// Newest first.
  Future<List<AppNotification>> getNotifications();

  /// Throws [NotFoundFailure] if unknown.
  Future<void> markAsRead(String id);

  Future<void> markAllAsRead();
}
