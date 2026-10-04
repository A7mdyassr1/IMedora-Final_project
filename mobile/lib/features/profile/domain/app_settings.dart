enum AppThemeMode { system, light, dark }

/// Preferences kept on THIS device (not in the IMedora database).
/// The notification switches are stored now and will drive push alerts once
/// the backend can send them.
class AppSettings {
  const AppSettings({
    this.themeMode = AppThemeMode.system,
    this.ticketUpdates = true,
    this.deviceAlerts = true,
  });

  final AppThemeMode themeMode;
  final bool ticketUpdates;
  final bool deviceAlerts;

  AppSettings copyWith({
    AppThemeMode? themeMode,
    bool? ticketUpdates,
    bool? deviceAlerts,
  }) =>
      AppSettings(
        themeMode: themeMode ?? this.themeMode,
        ticketUpdates: ticketUpdates ?? this.ticketUpdates,
        deviceAlerts: deviceAlerts ?? this.deviceAlerts,
      );
}
