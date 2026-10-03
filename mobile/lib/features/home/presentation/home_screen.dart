import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../../core/routing/app_router.dart';
import '../../../core/widgets/state_views.dart';
import '../../auth/presentation/auth_controller.dart';
import '../../tickets/presentation/ticket_tile.dart';
import '../../tickets/presentation/tickets_controller.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  String _greeting() {
    final h = DateTime.now().hour;
    if (h < 12) return 'Good morning';
    if (h < 18) return 'Good afternoon';
    return 'Good evening';
  }

  @override
  Widget build(BuildContext context) {
    final user = context.watch<AuthController>().user;
    final theme = Theme.of(context);
    final columns = MediaQuery.sizeOf(context).width >= 720 ? 4 : 2;

    return Scaffold(
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 900),
            child: ListView(
              padding: const EdgeInsets.all(20),
              children: [
                Text(_greeting(),
                    style: theme.textTheme.bodyLarge?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant)),
                Text(user?.fullName ?? '',
                    style: theme.textTheme.headlineSmall
                        ?.copyWith(fontWeight: FontWeight.w700)),
                const SizedBox(height: 4),
                Row(
                  children: [
                    Icon(Icons.local_hospital_outlined,
                        size: 16, color: theme.colorScheme.onSurfaceVariant),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        '${user?.hospitalName ?? ''}'
                        '${user != null ? ' - ${user.departmentName}' : ''}',
                        style: theme.textTheme.bodyMedium?.copyWith(
                            color: theme.colorScheme.onSurfaceVariant),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 24),
                const _SectionHeader(title: 'Quick actions'),
                GridView.count(
                  crossAxisCount: columns,
                  shrinkWrap: true,
                  physics: const NeverScrollableScrollPhysics(),
                  mainAxisSpacing: 12,
                  crossAxisSpacing: 12,
                  childAspectRatio: 1.5,
                  children: [
                    _QuickActionCard(
                      icon: Icons.qr_code_scanner,
                      label: 'Scan Device',
                      onTap: () => context.push(AppRoutes.scan),
                    ),
                    _QuickActionCard(
                      icon: Icons.report_problem_outlined,
                      label: 'Report Problem',
                      onTap: () => context.push(AppRoutes.report),
                    ),
                    _QuickActionCard(
                      icon: Icons.confirmation_number_outlined,
                      label: 'My Tickets',
                      onTap: () => context.go(AppRoutes.tickets),
                    ),
                    _QuickActionCard(
                      icon: Icons.smart_toy_outlined,
                      label: 'AI Assistant',
                      onTap: () => context.go(AppRoutes.ai),
                    ),
                  ],
                ),
                const SizedBox(height: 24),
                _SectionHeader(
                  title: 'Recent tickets',
                  actionLabel: 'See all',
                  onAction: () => context.go(AppRoutes.tickets),
                ),
                const _RecentTicketsSection(),
                const SizedBox(height: 24),
                const _SectionHeader(title: 'Notifications'),
                const _InfoCard(
                  icon: Icons.notifications_none,
                  message: "You're all caught up.",
                ),
                const SizedBox(height: 16),
              ],
            ),
          ),
        ),
      ),
    );
  }
}

class _SectionHeader extends StatelessWidget {
  const _SectionHeader({required this.title, this.actionLabel, this.onAction});
  final String title;
  final String? actionLabel;
  final VoidCallback? onAction;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Row(
        children: [
          Expanded(
            child: Text(title,
                style: Theme.of(context)
                    .textTheme
                    .titleMedium
                    ?.copyWith(fontWeight: FontWeight.w600)),
          ),
          if (actionLabel != null)
            TextButton(onPressed: onAction, child: Text(actionLabel!)),
        ],
      ),
    );
  }
}

class _QuickActionCard extends StatelessWidget {
  const _QuickActionCard(
      {required this.icon, required this.label, required this.onTap});
  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Card(
      clipBehavior: Clip.antiAlias,
      child: InkWell(
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: scheme.primaryContainer,
                  shape: BoxShape.circle,
                ),
                child: Icon(icon, color: scheme.onPrimaryContainer),
              ),
              const SizedBox(height: 8),
              Text(label,
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.titleSmall),
            ],
          ),
        ),
      ),
    );
  }
}

class _InfoCard extends StatelessWidget {
  const _InfoCard({required this.icon, required this.message});
  final IconData icon;
  final String message;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Row(
          children: [
            Icon(icon, color: scheme.onSurfaceVariant),
            const SizedBox(width: 12),
            Expanded(
              child: Text(message,
                  style: TextStyle(color: scheme.onSurfaceVariant)),
            ),
          ],
        ),
      ),
    );
  }
}

class _RecentTicketsSection extends StatefulWidget {
  const _RecentTicketsSection();

  @override
  State<_RecentTicketsSection> createState() => _RecentTicketsSectionState();
}

class _RecentTicketsSectionState extends State<_RecentTicketsSection> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (mounted) context.read<TicketsController>().ensureLoaded();
    });
  }

  @override
  Widget build(BuildContext context) {
    final c = context.watch<TicketsController>();
    switch (c.status) {
      case LoadStatus.idle:
      case LoadStatus.loading:
        return const Padding(
          padding: EdgeInsets.symmetric(vertical: 16),
          child: LoadingView(message: 'Loading tickets...'),
        );
      case LoadStatus.error:
        return ErrorView(
          message: c.error ?? 'Unable to load tickets.',
          onRetry: () => c.load(),
        );
      case LoadStatus.loaded:
        if (c.tickets.isEmpty) {
          return const _InfoCard(
            icon: Icons.confirmation_number_outlined,
            message: 'No tickets yet. Problems you report will appear here.',
          );
        }
        return Column(
          children: [for (final t in c.tickets.take(3)) TicketTile(ticket: t)],
        );
    }
  }
}
