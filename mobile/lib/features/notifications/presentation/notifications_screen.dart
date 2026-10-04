import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../core/widgets/state_views.dart';
import '../../tickets/presentation/tickets_controller.dart' show LoadStatus;
import 'notification_tile.dart';
import 'notifications_controller.dart';

class NotificationsScreen extends StatefulWidget {
  const NotificationsScreen({super.key});

  @override
  State<NotificationsScreen> createState() => _NotificationsScreenState();
}

class _NotificationsScreenState extends State<NotificationsScreen> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) context.read<NotificationsController>().ensureLoaded();
    });
  }

  @override
  Widget build(BuildContext context) {
    final c = context.watch<NotificationsController>();
    final canMarkAll = c.status == LoadStatus.loaded && c.unreadCount > 0;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Notifications'),
        actions: [
          if (canMarkAll)
            TextButton(
              onPressed: c.markAllAsRead,
              child: const Text('Mark all read'),
            ),
        ],
      ),
      body: switch (c.status) {
        LoadStatus.idle ||
        LoadStatus.loading =>
          const LoadingView(message: 'Loading notifications...'),
        LoadStatus.error => ErrorView(
            message: c.error ?? 'Unable to load notifications.',
            onRetry: () => c.load(),
          ),
        LoadStatus.loaded => c.items.isEmpty
            ? const EmptyView(
                icon: Icons.notifications_none,
                message: 'No notifications yet.',
              )
            : Align(
                alignment: Alignment.topCenter,
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 720),
                  child: RefreshIndicator(
                    onRefresh: () => c.load(silent: true),
                    child: ListView.separated(
                      padding: const EdgeInsets.symmetric(vertical: 8),
                      itemCount: c.items.length,
                      separatorBuilder: (_, _) => const Divider(height: 1),
                      itemBuilder: (context, i) =>
                          NotificationTile(notification: c.items[i]),
                    ),
                  ),
                ),
              ),
      },
    );
  }
}
