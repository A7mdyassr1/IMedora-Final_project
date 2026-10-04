import 'package:flutter_test/flutter_test.dart';
import 'package:imedora_mobile/core/errors/failures.dart';
import 'package:imedora_mobile/features/auth/data/mock_auth_repository.dart';

void main() {
  final repo = MockAuthRepository();

  test('demo credentials log in', () async {
    final s = await repo.login('demo@imedora.local', 'Demo123!');
    expect(s.user.role, 'department_user');
    expect(await repo.restoreSession(s.token), isNotNull);
  });

  test('wrong password is rejected', () async {
    expect(() => repo.login('demo@imedora.local', 'nope'),
        throwsA(isA<AuthFailure>()));
  });

  test('unknown token does not restore a session', () async {
    expect(await repo.restoreSession('garbage'), isNull);
  });
}
