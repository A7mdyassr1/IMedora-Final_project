import 'package:flutter/foundation.dart';

import '../../../core/errors/failures.dart';
import '../../auth/presentation/auth_controller.dart';
import '../../tickets/presentation/tickets_controller.dart' show LoadStatus;
import '../domain/notification.dart';
import '../domain/notification_repository.dart';

/// Shared notifications state: Home (bell badge + preview) and the
/// Notifications screen read the same list and the same unread count.
class NotificationsController extends ChangeNotifier {
  NotificationsController(this._repo, this._auth) {
    _auth.addListener(_onAuthChanged);
  }

  final NotificationRepository _repo;
  final AuthController _auth;

  LoadStatus _status = LoadStatus.idle;
  List<AppNotification> _items = const [];
  String? _error;
  int _loadId = 0;
  bool _disposed = false;

  LoadStatus get status => _status;
  List<AppNotification> get items => _items;
  String? get error => _error;
  int get unreadCount => _items.where((n) => !n.isRead).length;

  void ensureLoaded() {
    if (_status == LoadStatus.idle) load();
  }

  Future<void> load({bool silent = false}) async {
    final id = ++_loadId;
    final keepData = silent && _status == LoadStatus.loaded;
    if (!keepData) {
      _status = LoadStatus.loading;
      _error = null;
      _notify();
    }
    try {
      final result = await _repo.getNotifications();
      if (id != _loadId || _disposed) return;
      _items = result;
      _status = LoadStatus.loaded;
      _error = null;
    } on Failure catch (f) {
      if (id != _loadId || _disposed || keepData) return;
      _status = LoadStatus.error;
      _error = f.message;
    } catch (_) {
      if (id != _loadId || _disposed || keepData) return;
      _status = LoadStatus.error;
      _error = 'Unable to load notifications.';
    }
    _notify();
  }

  /// Updates the UI immediately, then tells the repository.
  /// If that fails, reload to get back in sync with the server.
  Future<void> markAsRead(String id) async {
    final i = _items.indexWhere((n) => n.id == id);
    if (i == -1 || _items[i].isRead) return;
    final updated = [..._items];
    updated[i] = updated[i].markRead(DateTime.now());
    _items = updated;
    _notify();
    try {
      await _repo.markAsRead(id);
    } catch (_) {
      load(silent: true);
    }
  }

  Future<void> markAllAsRead() async {
    if (unreadCount == 0) return;
    final now = DateTime.now();
    _items = [for (final n in _items) n.isRead ? n : n.markRead(now)];
    _notify();
    try {
      await _repo.markAllAsRead();
    } catch (_) {
      load(silent: true);
    }
  }

  void _onAuthChanged() {
    if (!_auth.isAuthenticated && _status != LoadStatus.idle) reset();
  }

  /// Clears everything (on logout).
  void reset() {
    _loadId++;
    _status = LoadStatus.idle;
    _items = const [];
    _error = null;
    _notify();
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    _auth.removeListener(_onAuthChanged);
    super.dispose();
  }
}
