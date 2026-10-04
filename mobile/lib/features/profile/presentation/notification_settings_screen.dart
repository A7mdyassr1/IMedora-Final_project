import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'settings_controller.dart';

class NotificationSettingsScreen extends StatelessWidget {
  const NotificationSettingsScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final c = context.watch<SettingsController>();
    final s = c.settings;
    final theme = Theme.of(context);

    return Scaffold(
      appBar: AppBar(title: const Text('Notification settings')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          Center(
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 640),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Card(
                    child: Column(
                      children: [
                        SwitchListTile(
                          secondary: const Icon(Icons.confirmation_number_outlined),
                          title: const Text('Ticket updates'),
                          subtitle: const Text(
                              'When your tickets are received, assigned, updated or resolved.'),
                          value: s.ticketUpdates,
                          onChanged: c.setTicketUpdates,
                        ),
                        const Divider(height: 1),
                        SwitchListTile(
                          secondary: const Icon(Icons.warning_amber_outlined),
                          title: const Text('Device alerts'),
                          subtitle: const Text(
                              'Important notices about devices in your department.'),
                          value: s.deviceAlerts,
                          onChanged: c.setDeviceAlerts,
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 12),
                  Text(
                    'Saved on this device. They will control push alerts once the app is connected to the hospital server.',
                    style: theme.textTheme.bodySmall
                        ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}
