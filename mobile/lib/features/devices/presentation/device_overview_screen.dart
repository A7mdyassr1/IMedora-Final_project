import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../../core/errors/failures.dart';
import '../../../core/routing/app_router.dart';
import '../../../core/utils/date_format.dart';
import '../../../core/widgets/state_views.dart';
import '../domain/device.dart';
import '../domain/device_repository.dart';
import 'device_badges.dart';

class DeviceOverviewScreen extends StatefulWidget {
  const DeviceOverviewScreen({super.key, required this.deviceId});
  final String deviceId;

  @override
  State<DeviceOverviewScreen> createState() => _DeviceOverviewScreenState();
}

class _DeviceOverviewScreenState extends State<DeviceOverviewScreen> {
  late Future<Device> _future;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() {
    _future = context.read<DeviceRepository>().getById(widget.deviceId);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Device')),
      body: FutureBuilder<Device>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const LoadingView(message: 'Loading device...');
          }
          if (snap.hasError) {
            final e = snap.error;
            return ErrorView(
              message: e is Failure
                  ? e.message
                  : 'Unable to load device information.',
              onRetry: () => setState(_load),
            );
          }
          return _DeviceBody(device: snap.data!);
        },
      ),
    );
  }
}

class _DeviceBody extends StatelessWidget {
  const _DeviceBody({required this.device});
  final Device device;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final warranty = device.warrantyStatus();
    final expiry = device.warrantyExpiry;

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 640),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(20),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Container(
                              padding: const EdgeInsets.all(12),
                              decoration: BoxDecoration(
                                color: theme.colorScheme.primaryContainer,
                                borderRadius: BorderRadius.circular(14),
                              ),
                              child: Icon(Icons.monitor_heart_outlined,
                                  size: 32,
                                  color: theme.colorScheme.onPrimaryContainer),
                            ),
                            const SizedBox(width: 16),
                            Expanded(
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Text(device.name,
                                      style: theme.textTheme.titleLarge
                                          ?.copyWith(
                                              fontWeight: FontWeight.w700)),
                                  const SizedBox(height: 2),
                                  Text('Device code: ${device.deviceCode}',
                                      style: theme.textTheme.bodyMedium
                                          ?.copyWith(
                                              color: theme.colorScheme
                                                  .onSurfaceVariant)),
                                ],
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 16),
                        Wrap(
                          spacing: 8,
                          runSpacing: 8,
                          children: [
                            DeviceStatusChip(status: device.status),
                            CriticalityChip(criticality: device.criticality),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                Card(
                  child: Column(
                    children: [
                      _InfoRow(
                          icon: Icons.factory_outlined,
                          label: 'Manufacturer',
                          value: device.manufacturer),
                      const Divider(height: 1),
                      _InfoRow(
                          icon: Icons.devices_other_outlined,
                          label: 'Model',
                          value: device.model),
                      const Divider(height: 1),
                      _InfoRow(
                          icon: Icons.apartment_outlined,
                          label: 'Department',
                          value: device.department),
                      const Divider(height: 1),
                      _InfoRow(
                          icon: Icons.place_outlined,
                          label: 'Location',
                          value: device.location ?? 'Not specified'),
                      const Divider(height: 1),
                      _InfoRow(
                        icon: Icons.verified_user_outlined,
                        label: 'Warranty',
                        child: Wrap(
                          spacing: 8,
                          runSpacing: 4,
                          crossAxisAlignment: WrapCrossAlignment.center,
                          children: [
                            WarrantyChip(status: warranty),
                            if (expiry != null)
                              Text('until ${formatDate(expiry)}',
                                  style: theme.textTheme.bodyMedium),
                          ],
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 20),
                FilledButton.icon(
                  icon: const Icon(Icons.report_problem_outlined),
                  label: const Text('Report Problem'),
                  onPressed: () => context
                      .push(AppRoutes.reportPath(deviceId: device.id)),
                ),
                const SizedBox(height: 12),
                OutlinedButton.icon(
                  style: OutlinedButton.styleFrom(
                      minimumSize: const Size.fromHeight(52)),
                  icon: const Icon(Icons.history),
                  label: const Text('View Ticket History'),
                  onPressed: () => context
                      .push(AppRoutes.deviceTicketsPath(device.id)),
                ),
                const SizedBox(height: 12),
                OutlinedButton.icon(
                  style: OutlinedButton.styleFrom(
                      minimumSize: const Size.fromHeight(52)),
                  icon: const Icon(Icons.smart_toy_outlined),
                  label: const Text('Ask AI'),
                  onPressed: () => context
                      .push(AppRoutes.assistantPath(deviceId: device.id)),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _InfoRow extends StatelessWidget {
  const _InfoRow({required this.icon, required this.label, this.value, this.child});
  final IconData icon;
  final String label;
  final String? value;
  final Widget? child;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(icon, color: theme.colorScheme.onSurfaceVariant),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(label,
                    style: theme.textTheme.labelMedium
                        ?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
                const SizedBox(height: 2),
                child ?? Text(value ?? '', style: theme.textTheme.bodyLarge),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
