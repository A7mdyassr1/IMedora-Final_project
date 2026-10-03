import 'dart:io';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../../../core/errors/failures.dart';
import '../../../core/routing/app_router.dart';
import '../../../core/utils/date_format.dart';
import '../../../core/widgets/state_views.dart';
import '../domain/ticket.dart';
import '../domain/ticket_repository.dart';
import 'ticket_badges.dart';

/// Read-only for hospital staff: they follow the ticket, the biomedical team
/// updates it (from the web app).
class TicketDetailsScreen extends StatefulWidget {
  const TicketDetailsScreen({super.key, required this.ticketId});
  final String ticketId;

  @override
  State<TicketDetailsScreen> createState() => _TicketDetailsScreenState();
}

class _TicketDetailsScreenState extends State<TicketDetailsScreen> {
  late Future<Ticket> _future;

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() {
    _future = context.read<TicketRepository>().getTicketById(widget.ticketId);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Ticket')),
      body: FutureBuilder<Ticket>(
        future: _future,
        builder: (context, snap) {
          if (snap.connectionState != ConnectionState.done) {
            return const LoadingView(message: 'Loading ticket...');
          }
          if (snap.hasError) {
            final e = snap.error;
            return ErrorView(
              message: e is Failure ? e.message : 'Unable to load ticket.',
              onRetry: () => setState(_load),
            );
          }
          return _TicketBody(ticket: snap.data!);
        },
      ),
    );
  }
}

class _TicketBody extends StatelessWidget {
  const _TicketBody({required this.ticket});
  final Ticket ticket;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    final updates = [...ticket.updates]..sort((a, b) => b.at.compareTo(a.at));

    return ListView(
      padding: const EdgeInsets.all(16),
      children: [
        Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 640),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                // Header: id, status, priority, created date
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(20),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(ticket.number,
                            style: theme.textTheme.titleLarge
                                ?.copyWith(fontWeight: FontWeight.w700)),
                        const SizedBox(height: 4),
                        Text('Reported ${formatDateTime(ticket.createdAt)}',
                            style: theme.textTheme.bodyMedium
                                ?.copyWith(color: scheme.onSurfaceVariant)),
                        if (ticket.resolvedAt != null)
                          Text('Resolved ${formatDateTime(ticket.resolvedAt!)}',
                              style: theme.textTheme.bodyMedium
                                  ?.copyWith(color: scheme.onSurfaceVariant)),
                        const SizedBox(height: 12),
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
                const SizedBox(height: 12),
                // Device (tap to open its overview)
                Card(
                  child: ListTile(
                    leading: const Icon(Icons.monitor_heart_outlined),
                    title: Text(ticket.deviceName),
                    subtitle: Text('Device code: ${ticket.deviceCode}'),
                    trailing: const Icon(Icons.chevron_right),
                    onTap: () =>
                        context.push(AppRoutes.devicePath(ticket.deviceId)),
                  ),
                ),
                const SizedBox(height: 12),
                // Problem
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const _SectionTitle('Problem'),
                        Text(ticket.category.label,
                            style: theme.textTheme.labelLarge
                                ?.copyWith(color: scheme.primary)),
                        const SizedBox(height: 6),
                        Text(ticket.description,
                            style: theme.textTheme.bodyLarge),
                      ],
                    ),
                  ),
                ),
                if (ticket.attachments.isNotEmpty) ...[
                  const SizedBox(height: 12),
                  Card(
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const _SectionTitle('Attachments'),
                          Wrap(
                            spacing: 8,
                            runSpacing: 8,
                            children: [
                              for (final a in ticket.attachments)
                                _AttachmentThumb(attachment: a),
                            ],
                          ),
                        ],
                      ),
                    ),
                  ),
                ],
                const SizedBox(height: 12),
                // Updates / history (newest first)
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const _SectionTitle('Updates'),
                        if (updates.isEmpty)
                          Text('No updates yet.',
                              style: theme.textTheme.bodyMedium
                                  ?.copyWith(color: scheme.onSurfaceVariant))
                        else
                          for (var i = 0; i < updates.length; i++)
                            _UpdateRow(
                              update: updates[i],
                              isFirst: i == 0,
                              isLast: i == updates.length - 1,
                            ),
                      ],
                    ),
                  ),
                ),
                const SizedBox(height: 16),
                Text(
                  'You can follow this ticket here. The biomedical team will update its status.',
                  textAlign: TextAlign.center,
                  style: theme.textTheme.bodySmall
                      ?.copyWith(color: scheme.onSurfaceVariant),
                ),
                const SizedBox(height: 16),
              ],
            ),
          ),
        ),
      ],
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.text);
  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Text(text,
          style: Theme.of(context)
              .textTheme
              .titleSmall
              ?.copyWith(fontWeight: FontWeight.w700)),
    );
  }
}

class _UpdateRow extends StatelessWidget {
  const _UpdateRow({
    required this.update,
    required this.isFirst,
    required this.isLast,
  });
  final TicketUpdate update;
  final bool isFirst;
  final bool isLast;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final scheme = theme.colorScheme;
    return IntrinsicHeight(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          SizedBox(
            width: 20,
            child: Column(
              children: [
                const SizedBox(height: 4),
                Container(
                  width: 12,
                  height: 12,
                  decoration: BoxDecoration(
                    shape: BoxShape.circle,
                    color: isFirst ? scheme.primary : scheme.outlineVariant,
                  ),
                ),
                if (!isLast)
                  Expanded(
                    child: Container(width: 2, color: scheme.outlineVariant),
                  ),
              ],
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Padding(
              padding: EdgeInsets.only(bottom: isLast ? 0 : 16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(update.status.label,
                      style: theme.textTheme.titleSmall
                          ?.copyWith(fontWeight: FontWeight.w600)),
                  const SizedBox(height: 2),
                  Text(update.message, style: theme.textTheme.bodyMedium),
                  const SizedBox(height: 2),
                  Text(formatDateTime(update.at),
                      style: theme.textTheme.bodySmall
                          ?.copyWith(color: scheme.onSurfaceVariant)),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _AttachmentImage extends StatelessWidget {
  const _AttachmentImage({required this.url, required this.fit});
  final String url;
  final BoxFit fit;

  @override
  Widget build(BuildContext context) {
    Widget broken(BuildContext c, Object e, StackTrace? s) => Container(
          color: Theme.of(c).colorScheme.surfaceContainerHighest,
          child: const Icon(Icons.broken_image_outlined),
        );
    if (url.startsWith('http')) {
      return Image.network(url, fit: fit, errorBuilder: broken);
    }
    return Image.file(File(url), fit: fit, errorBuilder: broken);
  }
}

class _AttachmentThumb extends StatelessWidget {
  const _AttachmentThumb({required this.attachment});
  final TicketAttachment attachment;

  void _open(BuildContext context) {
    showDialog<void>(
      context: context,
      builder: (dialogContext) => Dialog(
        child: Stack(
          children: [
            SizedBox(
              height: MediaQuery.sizeOf(dialogContext).height * 0.6,
              child: InteractiveViewer(
                child: Center(
                  child: _AttachmentImage(
                      url: attachment.fileUrl, fit: BoxFit.contain),
                ),
              ),
            ),
            Positioned(
              top: 4,
              right: 4,
              child: IconButton(
                tooltip: 'Close',
                icon: const Icon(Icons.close),
                onPressed: () => Navigator.of(dialogContext).pop(),
              ),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: 'Open photo ${attachment.fileName}',
      child: InkWell(
        onTap: () => _open(context),
        borderRadius: BorderRadius.circular(12),
        child: ClipRRect(
          borderRadius: BorderRadius.circular(12),
          child: SizedBox(
            width: 84,
            height: 84,
            child: _AttachmentImage(url: attachment.fileUrl, fit: BoxFit.cover),
          ),
        ),
      ),
    );
  }
}
