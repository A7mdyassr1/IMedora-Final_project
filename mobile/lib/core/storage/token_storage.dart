import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// Stores ONLY the session token (never the password).
abstract class TokenStorage {
  Future<String?> read();
  Future<void> write(String token);
  Future<void> clear();
}

class SecureTokenStorage implements TokenStorage {
  static const _key = 'imedora_session_token';
  final FlutterSecureStorage _storage = const FlutterSecureStorage();

  @override
  Future<String?> read() => _storage.read(key: _key);

  @override
  Future<void> write(String token) => _storage.write(key: _key, value: token);

  @override
  Future<void> clear() => _storage.delete(key: _key);
}
