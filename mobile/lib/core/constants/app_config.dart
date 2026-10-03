class AppConfig {
  AppConfig._();

  static const String appName = 'IMedora';

  /// Phase 1-8: everything runs on mock repositories.
  static const bool useMock = true;

  /// Used later by the real API client.
  /// Android emulator reaches the host machine at 10.0.2.2.
  /// Override with: flutter run --dart-define=API_BASE_URL=http://192.168.1.10:8000
  static const String apiBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://10.0.2.2:8000',
  );
}
