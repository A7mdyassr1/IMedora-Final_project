import 'package:flutter/material.dart';

import '../domain/device.dart';

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

class DeviceStatusChip extends StatelessWidget {
  const DeviceStatusChip({super.key, required this.status});
  final DeviceStatus status;

  @override
  Widget build(BuildContext context) {
    final (color, icon) = switch (status) {
      DeviceStatus.active => (Colors.green, Icons.check_circle_outline),
      DeviceStatus.underMaintenance => (Colors.orange, Icons.build_outlined),
      DeviceStatus.outOfService => (Colors.red, Icons.block),
      DeviceStatus.decommissioned => (Colors.grey, Icons.archive_outlined),
    };
    return _Badge(label: status.label, color: color, icon: icon);
  }
}

class CriticalityChip extends StatelessWidget {
  const CriticalityChip({super.key, required this.criticality});
  final DeviceCriticality criticality;

  @override
  Widget build(BuildContext context) {
    final color = switch (criticality) {
      DeviceCriticality.low => Colors.blueGrey,
      DeviceCriticality.medium => Colors.blue,
      DeviceCriticality.high => Colors.orange,
      DeviceCriticality.critical => Colors.red,
    };
    return _Badge(
      label: '${criticality.label} criticality',
      color: color,
      icon: Icons.priority_high,
    );
  }
}

class WarrantyChip extends StatelessWidget {
  const WarrantyChip({super.key, required this.status});
  final WarrantyStatus status;

  @override
  Widget build(BuildContext context) {
    final color = switch (status) {
      WarrantyStatus.active => Colors.green,
      WarrantyStatus.expiringSoon => Colors.orange,
      WarrantyStatus.expired => Colors.red,
      WarrantyStatus.unknown => Colors.grey,
    };
    return _Badge(
        label: status.label, color: color, icon: Icons.verified_user_outlined);
  }
}
