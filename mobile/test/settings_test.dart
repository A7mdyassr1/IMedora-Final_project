import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:imedora_mobile/features/profile/domain/app_settings.dart';
import 'package:imedora_mobile/features/profile/presentation/settings_controller.dart';

import 'test_fakes.dart';

void main() {
  test('defaults: system theme, notifications on', () {
    final c = SettingsController(MemorySettingsRepository());
    expect(c.themeMode, ThemeMode.system);
    expect(c.settings.ticketUpdates, isTrue);
    expect(c.settings.deviceAlerts, isTrue);
  });

  test('setThemeMode applies the theme and saves it', () async {
    final repo = MemorySettingsRepository();
    final c = SettingsController(repo);
    await c.setThemeMode(AppThemeMode.dark);
    expect(c.themeMode, ThemeMode.dark);
    expect(repo.stored.themeMode, AppThemeMode.dark);
  });

  test('notification switches are saved', () async {
    final repo = MemorySettingsRepository();
    final c = SettingsController(repo);
    await c.setTicketUpdates(false);
    await c.setDeviceAlerts(false);
    expect(repo.stored.ticketUpdates, isFalse);
    expect(repo.stored.deviceAlerts, isFalse);
  });

  test('load restores saved settings', () async {
    final repo = MemorySettingsRepository(const AppSettings(
      themeMode: AppThemeMode.light,
      ticketUpdates: false,
    ));
    final c = SettingsController(repo);
    await c.load();
    expect(c.themeMode, ThemeMode.light);
    expect(c.settings.ticketUpdates, isFalse);
    expect(c.settings.deviceAlerts, isTrue);
  });

  test('a failing save does not crash and the choice still applies', () async {
    final repo = MemorySettingsRepository()..failSaves = true;
    final c = SettingsController(repo);
    await c.setTicketUpdates(false);
    expect(c.settings.ticketUpdates, isFalse);
  });
}
