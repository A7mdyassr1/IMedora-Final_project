import 'package:flutter/material.dart';

import '../domain/app_settings.dart';
import '../domain/settings_repository.dart';

class SettingsController extends ChangeNotifier {
  SettingsController(this._repo);

  final SettingsRepository _repo;
  AppSettings _settings = const AppSettings();

  AppSettings get settings => _settings;

  ThemeMode get themeMode => switch (_settings.themeMode) {
        AppThemeMode.system => ThemeMode.system,
        AppThemeMode.light => ThemeMode.light,
        AppThemeMode.dark => ThemeMode.dark,
      };

  /// Called once at startup so the saved theme is used from the first frame.
  Future<void> load() async {
    try {
      _settings = await _repo.load();
    } catch (_) {
      // Keep defaults.
    }
    notifyListeners();
  }

  Future<void> setThemeMode(AppThemeMode mode) =>
      _update(_settings.copyWith(themeMode: mode));

  Future<void> setTicketUpdates(bool value) =>
      _update(_settings.copyWith(ticketUpdates: value));

  Future<void> setDeviceAlerts(bool value) =>
      _update(_settings.copyWith(deviceAlerts: value));

  /// UI updates immediately; saving is best-effort.
  Future<void> _update(AppSettings next) async {
    _settings = next;
    notifyListeners();
    try {
      await _repo.save(next);
    } catch (_) {
      // The choice still applies for this session.
    }
  }
}
