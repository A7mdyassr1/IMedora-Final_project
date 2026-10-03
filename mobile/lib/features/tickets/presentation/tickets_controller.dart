import 'package:flutter/foundation.dart';

import '../../../core/errors/failures.dart';
import '../../auth/presentation/auth_controller.dart';
import '../domain/ticket.dart';
import '../domain/ticket_repository.dart';

enum LoadStatus { idle, loading, loaded, error }

/// Shared "my tickets" state, used by Home (recent tickets) and the
/// My Tickets tab, so a newly reported ticket shows up in both.
class TicketsController extends ChangeNotifier {
  TicketsController(this._repo, this._auth) {
    _auth.addListener(_onAuthChanged);
  }

  final TicketRepository _repo;
  final AuthController _auth;

  LoadStatus _status = LoadStatus.idle;
  List<Ticket> _tickets = const [];
  String? _error;
  int _loadId = 0;
  bool _disposed = false;

  LoadStatus get status => _status;
  List<Ticket> get tickets => _tickets;
  String? get error => _error;

  /// Loads once; screens call this when they first appear.
  void ensureLoaded() {
    if (_status == LoadStatus.idle) load();
  }

  /// [silent] keeps showing the current list while refreshing
  /// (pull-to-refresh / after creating a ticket).
  Future<void> load({bool silent = false}) async {
    final id = ++_loadId;
    final keepData = silent && _status == LoadStatus.loaded;
    if (!keepData) {
      _status = LoadStatus.loading;
      _error = null;
      _notify();
    }
    try {
      final result = await _repo.getMyTickets();
      if (id != _loadId || _disposed) return;
      _tickets = result;
      _status = LoadStatus.loaded;
      _error = null;
    } on Failure catch (f) {
      if (id != _loadId || _disposed || keepData) return;
      _status = LoadStatus.error;
      _error = f.message;
    } catch (_) {
      if (id != _loadId || _disposed || keepData) return;
      _status = LoadStatus.error;
      _error = 'Unable to load tickets.';
    }
    _notify();
  }

  void _onAuthChanged() {
    if (!_auth.isAuthenticated && _status != LoadStatus.idle) reset();
  }

  /// Clears everything (on logout).
  void reset() {
    _loadId++;
    _status = LoadStatus.idle;
    _tickets = const [];
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
