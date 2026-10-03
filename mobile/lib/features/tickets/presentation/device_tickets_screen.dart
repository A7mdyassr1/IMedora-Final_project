import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../../core/errors/failures.dart';
import '../../../core/widgets/state_views.dart';
import '../domain/ticket.dart';
import '../domain/ticket_repository.dart';
import 'ticket_tile.dart';

/// "View Ticket History" from Device Overview: tickets of ONE device.
class DeviceTicketsScreen extends StatefulWidget {
  const DeviceTicketsScreen({super.key, required this.deviceId});
  final String deviceId;

  @override
  State<DeviceTicketsScreen> createState() => _DeviceTicketsScreenState();
}

class _DeviceTicketsScreenState extends State<DeviceTicketsScreen> {
  late Future<List<Ticket>> _future;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() {
    _future = context.read<TicketRepository>().getTicketsForDevice(widget.deviceId);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Ticket History')),
      body: FutureBuilder<List<Ticket>>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const LoadingView(message: 'Loading tickets...');
          }
          if (snap.hasError) {
            final e = snap.error;
            return ErrorView(
              message: e is Failure ? e.message : 'Unable to load tickets.',
              onRetry: () => setState(_load),
            );
          }
          final tickets = snap.data ?? const <Ticket>[];
          if (tickets.isEmpty) {
            return const EmptyView(
              icon: Icons.history,
              message: 'No tickets for this device.',
            );
          }
          return Align(
            alignment: Alignment.topCenter,
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 720),
              child: ListView.builder(
                padding: const EdgeInsets.fromLTRB(12, 8, 12, 24),
                itemCount: tickets.length,
                itemBuilder: (context, i) => TicketTile(ticket: tickets[i]),
              ),
            ),
          );
        },
      ),
    );
  }
}
