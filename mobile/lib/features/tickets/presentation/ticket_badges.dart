import 'package:flutter/material.dart';

import '../domain/ticket.dart';

class _Badge extends StatelessWidget {
  const _Badge({required this.label, required this.color, required this.icon});
  final String label;
  final MaterialColor color;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    final dark = Theme.of(context).brightness == Brightness.dark;
    final fg = dark ? color.shade200 : color.shade800;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.16),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: fg),
          const SizedBox(width: 4),
          Text(label,
              style: Theme.of(context)
                  .textTheme
                  .labelMedium
                  ?.copyWith(color: fg, fontWeight: FontWeight.w600)),
        ],
      ),
    );
  }
}

class TicketStatusChip extends StatelessWidget {
  const TicketStatusChip({super.key, required this.status});
  final TicketStatus status;

  @override
  Widget build(BuildContext context) {
    final (color, icon) = switch (status) {
      TicketStatus.open => (Colors.blue, Icons.inbox_outlined),
      TicketStatus.assigned => (Colors.indigo, Icons.person_outline),
      TicketStatus.inProgress => (Colors.orange, Icons.build_outlined),
      TicketStatus.waitingForParts => (Colors.amber, Icons.inventory_2_outlined),
      TicketStatus.resolved => (Colors.green, Icons.check_circle_outline),
      TicketStatus.closed => (Colors.blueGrey, Icons.lock_outline),
      TicketStatus.cancelled => (Colors.grey, Icons.cancel_outlined),
    };
    return _Badge(label: status.label, color: color, icon: icon);
  }
}

class TicketPriorityChip extends StatelessWidget {
  const TicketPriorityChip({super.key, required this.priority});
  final TicketPriority priority;

  @override
  Widget build(BuildContext context) {
    final color = switch (priority) {
      TicketPriority.low => Colors.blueGrey,
      TicketPriority.medium => Colors.blue,
      TicketPriority.high => Colors.orange,
      TicketPriority.critical => Colors.red,
    };
    return _Badge(
      label: '${priority.label} priority',
      color: color,
      icon: Icons.flag_outlined,
    );
  }
}
