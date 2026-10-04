import 'package:imedora_mobile/core/storage/token_storage.dart';
import 'package:imedora_mobile/features/profile/domain/app_settings.dart';
import 'package:imedora_mobile/features/profile/domain/settings_repository.dart';

class MemoryTokenStorage implements TokenStorage {
  String? token;
  @override
  Future<String?> read() async => token;
  @override
  Future<void> write(String t) async => token = t;
  @override
  Future<void> clear() async => token = null;
}

class MemorySettingsRepository implements SettingsRepository {
  MemorySettingsRepository([this.stored = const AppSettings()]);

  AppSettings stored;
  bool failSaves = false;

  @override
  Future<AppSettings> load() async => stored;

  @override
  Future<void> save(AppSettings settings) async {
    if (failSaves) throw Exception('disk full');
    stored = settings;
  }
}
