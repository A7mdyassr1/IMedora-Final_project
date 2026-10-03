import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../../core/routing/app_router.dart';
import '../../../core/widgets/state_views.dart';
import 'ticket_tile.dart';
import 'tickets_controller.dart';

class TicketsScreen extends StatefulWidget {
  const TicketsScreen({super.key});

  @override
  State<TicketsScreen> createState() => _TicketsScreenState();
}

class _TicketsScreenState extends State<TicketsScreen> {
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

    return Scaffold(
      appBar: AppBar(title: const Text('My Tickets')),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => context.push(AppRoutes.report),
        icon: const Icon(Icons.add),
        label: const Text('Report problem'),
      ),
      body: switch (c.status) {
        LoadStatus.idle ||
        LoadStatus.loading =>
          const LoadingView(message: 'Loading tickets...'),
        LoadStatus.error => ErrorView(
            message: c.error ?? 'Unable to load tickets.',
            onRetry: () => c.load(),
          ),
        LoadStatus.loaded => c.tickets.isEmpty
            ? const EmptyView(
                icon: Icons.confirmation_number_outlined,
                message: 'No tickets found.\nProblems you report will appear here.',
              )
            : Align(
                alignment: Alignment.topCenter,
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 720),
                  child: RefreshIndicator(
                    onRefresh: () => c.load(silent: true),
                    child: ListView.builder(
                      padding: const EdgeInsets.fromLTRB(12, 8, 12, 96),
                      itemCount: c.tickets.length,
                      itemBuilder: (context, i) =>
                          TicketTile(ticket: c.tickets[i]),
                    ),
                  ),
                ),
              ),
      },
    );
  }
}
