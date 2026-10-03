import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import 'core/routing/app_router.dart';
import 'core/theme/app_theme.dart';
import 'features/auth/presentation/auth_controller.dart';
import 'features/devices/domain/device_repository.dart';
import 'features/tickets/domain/ticket_repository.dart';
import 'features/tickets/presentation/tickets_controller.dart';

class ImedoraApp extends StatefulWidget {
  const ImedoraApp({
    super.key,
    required this.authController,
    required this.deviceRepository,
    required this.ticketRepository,
  });
  final AuthController authController;
  final DeviceRepository deviceRepository;
  final TicketRepository ticketRepository;

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
        Provider<DeviceRepository>.value(value: widget.deviceRepository),
        Provider<TicketRepository>.value(value: widget.ticketRepository),
        ChangeNotifierProvider<TicketsController>(
          create: (_) => TicketsController(
              widget.ticketRepository, widget.authController),
        ),
      ],
      child: MaterialApp.router(
        title: 'IMedora',
        debugShowCheckedModeBanner: false,
        theme: AppTheme.light(),
        darkTheme: AppTheme.dark(),
        themeMode: ThemeMode.system,
        routerConfig: _router,
      ),
    );
  }
}
