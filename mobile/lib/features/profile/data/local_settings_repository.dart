import 'dart:convert';

import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../domain/app_settings.dart';
import '../domain/settings_repository.dart';

/// Stores the (non-secret) preferences as one small JSON value.
/// Reuses flutter_secure_storage so no extra package is needed; it can be
/// swapped for shared_preferences without touching the rest of the app.
class LocalSettingsRepository implements SettingsRepository {
  LocalSettingsRepository({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  static const _key = 'imedora_app_settings';
  final FlutterSecureStorage _storage;

  @override
  Future<AppSettings> load() async {
    final raw = await _storage.read(key: _key);
    if (raw == null) return const AppSettings();
    try {
      final m = jsonDecode(raw) as Map<String, dynamic>;
      return AppSettings(
        themeMode: AppThemeMode.values.firstWhere(
          (t) => t.name == m['theme'],
          orElse: () => AppThemeMode.system,
        ),
        ticketUpdates: m['ticketUpdates'] as bool? ?? true,
        deviceAlerts: m['deviceAlerts'] as bool? ?? true,
      );
    } catch (_) {
      return const AppSettings();
    }
  }

  @override
  Future<void> save(AppSettings settings) => _storage.write(
        key: _key,
        value: jsonEncode({
          'theme': settings.themeMode.name,
          'ticketUpdates': settings.ticketUpdates,
          'deviceAlerts': settings.deviceAlerts,
        }),
      );
}
