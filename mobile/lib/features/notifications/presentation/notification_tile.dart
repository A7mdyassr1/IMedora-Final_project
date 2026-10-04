import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../../core/routing/app_router.dart';
import '../../../core/utils/date_format.dart';
import '../domain/notification.dart';
import 'notifications_controller.dart';

IconData _iconFor(NotificationType type) => switch (type) {
      NotificationType.ticketCreated => Icons.assignment_outlined,
      NotificationType.ticketAssigned => Icons.person_add_alt_outlined,
      NotificationType.ticketStatusChanged => Icons.sync_alt,
      NotificationType.ticketResolved => Icons.check_circle_outline,
      NotificationType.deviceAlert => Icons.warning_amber_outlined,
      NotificationType.other => Icons.notifications_none,
    };

/// One notification. Tapping marks it read and opens the related ticket
/// (if there is one).
class NotificationTile extends StatelessWidget {
  const NotificationTile({super.key, required this.notification});
  final AppNotification notification;

  void _open(BuildContext context) {
    final n = notification;
    context.read<NotificationsController>().markAsRead(n.id);
    final ticketId = n.relatedTicketId;
    if (ticketId != null) context.push(AppRoutes.ticketPath(ticketId));
  }

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final n = notification;
    final unread = !n.isRead;

    return ListTile(
      onTap: () => _open(context),
      tileColor: unread ? scheme.primaryContainer.withValues(alpha: 0.28) : null,
      leading: CircleAvatar(
        backgroundColor: scheme.primaryContainer,
        child: Icon(_iconFor(n.type), color: scheme.onPrimaryContainer),
      ),
      title: Text(
        n.title,
        style: TextStyle(fontWeight: unread ? FontWeight.w700 : FontWeight.w500),
      ),
      subtitle: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          if (n.body != null)
            Text(n.body!, maxLines: 2, overflow: TextOverflow.ellipsis),
          const SizedBox(height: 2),
          Text(formatRelative(n.createdAt),
              style: theme.textTheme.bodySmall
                  ?.copyWith(color: scheme.onSurfaceVariant)),
        ],
      ),
      trailing: unread
          ? Semantics(
              label: 'Unread',
              child: Container(
                width: 10,
                height: 10,
                decoration: BoxDecoration(
                  color: scheme.primary,
                  shape: BoxShape.circle,
                ),
              ),
            )
          : null,
    );
  }
}
