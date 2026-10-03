import 'auth_user.dart';

/// UI depends on this interface only.
/// Mock now -> ApiAuthRepository (POST /auth/login) later.
abstract class AuthRepository {
  /// Throws [AuthFailure] on bad credentials.
  Future<AuthSession> login(String identifier, String password);

  /// Returns the user for a stored token, or null if it is no longer valid.
  Future<AuthUser?> restoreSession(String token);

  Future<void> logout();
}
