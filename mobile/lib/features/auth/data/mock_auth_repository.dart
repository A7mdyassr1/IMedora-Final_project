import '../../../core/errors/failures.dart';
import '../domain/auth_repository.dart';
import '../domain/auth_user.dart';

/// Demo-only. Delete when the real backend auth exists.
/// Demo account: demo@imedora.local / Demo123!
class MockAuthRepository implements AuthRepository {
  static const _demoEmail = 'demo@imedora.local';
  static const _demoPassword = 'Demo123!';
  static const _mockToken = 'mock-session-token';

  static const _demoUser = AuthUser(
    id: '11111111-1111-1111-1111-111111111111',
    fullName: 'Dr. Sara Ahmed',
    email: _demoEmail,
    hospitalName: 'Cairo Medical Center - Main Campus',
    departmentName: 'ICU',
    role: 'department_user',
  );

  @override
  Future<AuthSession> login(String identifier, String password) async {
    await Future<void>.delayed(const Duration(milliseconds: 600));
    final id = identifier.trim().toLowerCase();
    final okId = id == _demoEmail || id == 'demo';
    if (okId && password == _demoPassword) {
      return const AuthSession(user: _demoUser, token: _mockToken);
    }
    throw const AuthFailure('Invalid email or password.');
  }

  @override
  Future<AuthUser?> restoreSession(String token) async {
    await Future<void>.delayed(const Duration(milliseconds: 150));
    return token == _mockToken ? _demoUser : null;
  }

  @override
  Future<void> logout() async {}
}
