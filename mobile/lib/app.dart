import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import 'core/routing/app_router.dart';
import 'core/theme/app_theme.dart';
import 'features/ai_assistant/domain/ai_assistant_service.dart';
import 'features/auth/presentation/auth_controller.dart';
import 'features/devices/domain/device_repository.dart';
import 'features/notifications/domain/notification_repository.dart';
import 'features/notifications/presentation/notifications_controller.dart';
import 'features/profile/presentation/settings_controller.dart';
import 'features/tickets/domain/ticket_repository.dart';
import 'features/tickets/presentation/tickets_controller.dart';

class ImedoraApp extends StatefulWidget {
  const ImedoraApp({
    super.key,
    required this.authController,
    required this.deviceRepository,
    required this.ticketRepository,
    required this.notificationRepository,
    required this.aiAssistantService,
    required this.settingsController,
  });
  final AuthController authController;
  final DeviceRepository deviceRepository;
  final TicketRepository ticketRepository;
  final NotificationRepository notificationRepository;
  final AiAssistantService aiAssistantService;
  final SettingsController settingsController;

  @override
  State<ImedoraApp> createState() => _ImedoraAppState();
}

class _ImedoraAppState extends State<ImedoraApp> {
  late final GoRouter _router = buildRouter(widget.authController);

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider<AuthController>.value(value: widget.authController),
        ChangeNotifierProvider<SettingsController>.value(
            value: widget.settingsController),
        Provider<DeviceRepository>.value(value: widget.deviceRepository),
        Provider<TicketRepository>.value(value: widget.ticketRepository),
        Provider<AiAssistantService>.value(value: widget.aiAssistantService),
        ChangeNotifierProvider<TicketsController>(
          create: (_) => TicketsController(
              widget.ticketRepository, widget.authController),
        ),
        ChangeNotifierProvider<NotificationsController>(
          create: (_) => NotificationsController(
              widget.notificationRepository, widget.authController),
        ),
      ],
      child: Consumer<SettingsController>(
        builder: (context, settings, _) => MaterialApp.router(
          title: 'IMedora',
          debugShowCheckedModeBanner: false,
          theme: AppTheme.light(),
          darkTheme: AppTheme.dark(),
          themeMode: settings.themeMode,
          routerConfig: _router,
        ),
      ),
    );
  }
}
