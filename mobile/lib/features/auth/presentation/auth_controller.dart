import 'package:flutter/foundation.dart';

import '../../../core/errors/failures.dart';
import '../../../core/storage/token_storage.dart';
import '../domain/auth_repository.dart';
import '../domain/auth_user.dart';

class AuthController extends ChangeNotifier {
  AuthController(this._repo, this._storage);

  final AuthRepository _repo;
  final TokenStorage _storage;

  AuthUser? _user;
  bool _isLoading = false;
  String? _error;

  AuthUser? get user => _user;
  bool get isAuthenticated => _user != null;
  bool get isLoading => _isLoading;
  String? get error => _error;

  /// Called once at startup (before the first frame).
  Future<void> restoreSession() async {
    try {
      final token = await _storage.read();
      if (token != null) {
        _user = await _repo.restoreSession(token);
        if (_user == null) await _storage.clear();
      }
    } catch (_) {
      _user = null;
    }
    notifyListeners();
  }

  Future<bool> login(String identifier, String password) async {
    _isLoading = true;
    _error = null;
    notifyListeners();
    try {
      final session = await _repo.login(identifier, password);
      await _storage.write(session.token);
      _user = session.user;
      _isLoading = false;
      notifyListeners();
      return true;
    } on Failure catch (f) {
      _error = f.message;
    } catch (_) {
      _error = 'Something went wrong. Please try again.';
    }
    _isLoading = false;
    notifyListeners();
    return false;
  }

  Future<void> logout() async {
    try {
      await _repo.logout();
    } catch (_) {}
    await _storage.clear();
    _user = null;
    _error = null;
    notifyListeners(); // router redirect sends the user to /login
  }
}
