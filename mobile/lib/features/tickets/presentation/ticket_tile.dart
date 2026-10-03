import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../../../core/routing/app_router.dart';
import '../../../core/utils/date_format.dart';
import '../domain/ticket.dart';
import 'ticket_badges.dart';

/// One ticket in a list: id, device, problem, priority, status, date.
class TicketTile extends StatelessWidget {
  const TicketTile({super.key, required this.ticket});
  final Ticket ticket;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: () => context.push(AppRoutes.ticketPath(ticket.id)),
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Text(ticket.number,
                      style: theme.textTheme.labelLarge?.copyWith(
                          color: scheme.primary, fontWeight: FontWeight.w700)),
                  const Spacer(),
                  Text(formatDate(ticket.createdAt),
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: scheme.onSurfaceVariant)),
                ],
              ),
              const SizedBox(height: 6),
              Text('${ticket.deviceName} (${ticket.deviceCode})',
                  style: theme.textTheme.titleMedium
                      ?.copyWith(fontWeight: FontWeight.w600)),
              const SizedBox(height: 4),
              Text(
                '${ticket.category.label} - ${ticket.description}',
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: theme.textTheme.bodyMedium
                    ?.copyWith(color: scheme.onSurfaceVariant),
              ),
              const SizedBox(height: 10),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  TicketStatusChip(status: ticket.status),
                  TicketPriorityChip(priority: ticket.priority),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}
