import 'package:flutter/material.dart';

import 'app.dart';
import 'core/storage/token_storage.dart';
import 'features/ai_assistant/data/mock_ai_assistant_service.dart';
import 'features/ai_assistant/domain/ai_assistant_service.dart';
import 'features/auth/data/mock_auth_repository.dart';
import 'features/auth/domain/auth_repository.dart';
import 'features/auth/presentation/auth_controller.dart';
import 'features/devices/data/mock_device_repository.dart';
import 'features/devices/domain/device_repository.dart';
import 'features/notifications/data/mock_notification_repository.dart';
import 'features/notifications/domain/notification_repository.dart';
import 'features/profile/data/local_settings_repository.dart';
import 'features/profile/domain/settings_repository.dart';
import 'features/profile/presentation/settings_controller.dart';
import 'features/tickets/data/mock_ticket_repository.dart';
import 'features/tickets/domain/ticket_repository.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // ---- Composition root: the ONLY place that picks Mock vs real API. ----
  // Later: Api*Repository(apiClient) for auth/devices/tickets/notifications
  // and BackendAiAssistantService(apiClient). Settings stay local.
  final AuthRepository authRepo = MockAuthRepository();
  final DeviceRepository deviceRepo = MockDeviceRepository();
  final mockNotifications = MockNotificationRepository();
  final NotificationRepository notificationRepo = mockNotifications;
  // Mock-only wiring: reporting a ticket creates a notification. With the real
  // backend the server does this, so this line simply disappears.
  final TicketRepository ticketRepo = MockTicketRepository(
    deviceRepo,
    onTicketCreated: mockNotifications.onTicketCreated,
  );
  final AiAssistantService aiService =
      MockAiAssistantService(deviceRepo, ticketRepo);
  final SettingsRepository settingsRepo = LocalSettingsRepository();
  final TokenStorage tokenStorage = SecureTokenStorage();

  final authController = AuthController(authRepo, tokenStorage);
  await authController.restoreSession();

  // Loaded before the first frame so the saved theme is used immediately.
  final settingsController = SettingsController(settingsRepo);
  await settingsController.load();

  runApp(ImedoraApp(
    authController: authController,
    deviceRepository: deviceRepo,
    ticketRepository: ticketRepo,
    notificationRepository: notificationRepo,
    aiAssistantService: aiService,
    settingsController: settingsController,
  ));
}
