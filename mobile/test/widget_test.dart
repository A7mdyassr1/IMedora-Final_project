import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:imedora_mobile/app.dart';
import 'package:imedora_mobile/core/storage/token_storage.dart';
import 'package:imedora_mobile/features/ai_assistant/data/mock_ai_assistant_service.dart';
import 'package:imedora_mobile/features/auth/data/mock_auth_repository.dart';
import 'package:imedora_mobile/features/auth/presentation/auth_controller.dart';
import 'package:imedora_mobile/features/devices/data/mock_device_repository.dart';
import 'package:imedora_mobile/features/notifications/data/mock_notification_repository.dart';
import 'package:imedora_mobile/features/profile/presentation/settings_controller.dart';
import 'package:imedora_mobile/features/tickets/data/mock_ticket_repository.dart';

import 'test_fakes.dart';

class _TestTokenStorage implements TokenStorage {
  @override
  Future<void> clear() async {}

  @override
  Future<String?> read() async => null;

  @override
  Future<void> write(String token) async {}
}

void main() {
  testWidgets('IMedora app builds successfully', (WidgetTester tester) async {
    final authController = AuthController(
      MockAuthRepository(),
      _TestTokenStorage(),
    );
    await authController.restoreSession();

    final deviceRepository = MockDeviceRepository();
    final ticketRepository = MockTicketRepository(deviceRepository);

    await tester.pumpWidget(
      ImedoraApp(
        authController: authController,
        deviceRepository: deviceRepository,
        ticketRepository: ticketRepository,
        notificationRepository: MockNotificationRepository(),
        aiAssistantService:
            MockAiAssistantService(deviceRepository, ticketRepository),
        settingsController: SettingsController(MemorySettingsRepository()),
      ),
    );

    expect(find.byType(MaterialApp), findsOneWidget);
  });
}
