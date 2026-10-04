import 'dart:io';

import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:image_picker/image_picker.dart';
import 'package:provider/provider.dart';

import '../../../core/errors/failures.dart';
import '../../../core/routing/app_router.dart';
import '../../../core/widgets/state_views.dart';
import '../../devices/domain/device.dart';
import '../../devices/domain/device_repository.dart';
import '../../notifications/presentation/notifications_controller.dart';
import '../domain/ticket.dart';
import '../domain/ticket_repository.dart';
import 'tickets_controller.dart';

const int _maxPhotos = 3;

/// Opened from Device Overview (device preselected) or from Home
/// (user picks the device).
class ReportProblemScreen extends StatefulWidget {
  const ReportProblemScreen({super.key, this.deviceId});
  final String? deviceId;

  @override
  State<ReportProblemScreen> createState() => _ReportProblemScreenState();
}

class _ReportProblemScreenState extends State<ReportProblemScreen> {
  final _formKey = GlobalKey<FormState>();
  final _descCtrl = TextEditingController();
  final _picker = ImagePicker();

  Device? _device;
  bool _loadingDevice = false;
  String? _deviceLoadError;
  ProblemCategory? _category;
  TicketPriority? _priority;
  final List<String> _photos = [];
  bool _submitting = false;
  String? _error;
  Ticket? _created;

  @override
  void initState() {
    super.initState();
    final id = widget.deviceId;
    if (id != null) {
      _loadingDevice = true;
      _fetchDevice(id);
    }
  }

  @override
  void dispose() {
    _descCtrl.dispose();
    super.dispose();
  }

  Future<void> _fetchDevice(String id) async {
    final repo = context.read<DeviceRepository>();
    try {
      final d = await repo.getById(id);
      if (!mounted) return;
      setState(() {
        _device = d;
        _loadingDevice = false;
      });
    } on Failure catch (f) {
      _deviceFailed(f.message);
    } catch (_) {
      _deviceFailed('Unable to load device information.');
    }
  }

  void _deviceFailed(String message) {
    if (!mounted) return;
    setState(() {
      _loadingDevice = false;
      _deviceLoadError = message;
    });
  }

  void _snack(String message) {
    ScaffoldMessenger.of(context)
      ..hideCurrentSnackBar()
      ..showSnackBar(SnackBar(content: Text(message)));
  }

  Future<void> _pickDevice() async {
    final device = await showModalBottomSheet<Device>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => const _DevicePickerSheet(),
    );
    if (device != null && mounted) {
      setState(() {
        _device = device;
        _deviceLoadError = null;
      });
    }
  }

  Future<void> _addPhoto() async {
    if (_photos.length >= _maxPhotos) {
      _snack('You can attach up to $_maxPhotos photos.');
      return;
    }
    final source = await showModalBottomSheet<ImageSource>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) => SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            ListTile(
              leading: const Icon(Icons.photo_camera_outlined),
              title: const Text('Take a photo'),
              onTap: () =>
                  Navigator.of(sheetContext).pop(ImageSource.camera),
            ),
            ListTile(
              leading: const Icon(Icons.photo_library_outlined),
              title: const Text('Choose from gallery'),
              onTap: () =>
                  Navigator.of(sheetContext).pop(ImageSource.gallery),
            ),
          ],
        ),
      ),
    );
    if (source == null) return;
    try {
      final file = await _picker.pickImage(
        source: source,
        maxWidth: 1600,
        imageQuality: 80,
      );
      if (file == null || !mounted) return;
      setState(() => _photos.add(file.path));
    } catch (_) {
      if (mounted) _snack('Unable to open the camera or gallery.');
    }
  }

  Future<void> _submit() async {
    if (_submitting) return;
    if (!_formKey.currentState!.validate()) return;
    FocusScope.of(context).unfocus();
    setState(() {
      _submitting = true;
      _error = null;
    });
    final repo = context.read<TicketRepository>();
    try {
      final ticket = await repo.createTicket(NewTicketRequest(
        deviceId: _device!.id,
        category: _category!,
        description: _descCtrl.text.trim(),
        priority: _priority,
        attachmentPaths: List.of(_photos),
      ));
      if (!mounted) return;
      context.read<TicketsController>().load(silent: true);
      context.read<NotificationsController>().load(silent: true);
      setState(() {
        _created = ticket;
        _submitting = false;
      });
    } on Failure catch (f) {
      if (!mounted) return;
      setState(() {
        _error = f.message;
        _submitting = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _error = 'Could not send your report. Please try again.';
        _submitting = false;
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final created = _created;
    if (created != null) return _SuccessView(ticket: created);

    final theme = Theme.of(context);
    final scheme = theme.colorScheme;

    return Scaffold(
      appBar: AppBar(title: const Text('Report Problem')),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 640),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const _FieldLabel('Device'),
                    FormField<Device>(
                      validator: (_) =>
                          _device == null ? 'Please select the device' : null,
                      builder: (state) => Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Card(child: _deviceTile()),
                          if (state.hasError)
                            Padding(
                              padding: const EdgeInsets.only(left: 16, top: 6),
                              child: Text(state.errorText!,
                                  style: TextStyle(
                                      color: scheme.error, fontSize: 12)),
                            ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 20),
                    const _FieldLabel('What is the problem?'),
                    FormField<ProblemCategory>(
                      validator: (_) =>
                          _category == null ? 'Please choose a category' : null,
                      builder: (state) => Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Wrap(
                            spacing: 8,
                            runSpacing: 8,
                            children: [
                              for (final c in ProblemCategory.values)
                                ChoiceChip(
                                  label: Text(c.label),
                                  selected: _category == c,
                                  onSelected: (_) {
                                    setState(() => _category = c);
                                    state.didChange(c);
                                  },
                                ),
                            ],
                          ),
                          if (state.hasError)
                            Padding(
                              padding: const EdgeInsets.only(top: 6),
                              child: Text(state.errorText!,
                                  style: TextStyle(
                                      color: scheme.error, fontSize: 12)),
                            ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 20),
                    const _FieldLabel('Description'),
                    TextFormField(
                      controller: _descCtrl,
                      minLines: 4,
                      maxLines: 6,
                      maxLength: 500,
                      textCapitalization: TextCapitalization.sentences,
                      decoration: const InputDecoration(
                        hintText:
                            'What happened? Mention any alarm or error message.',
                      ),
                      validator: (v) => (v == null || v.trim().length < 10)
                          ? 'Please describe the problem (at least 10 characters)'
                          : null,
                    ),
                    const SizedBox(height: 12),
                    const _FieldLabel('Priority (optional)'),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        for (final p in TicketPriority.values)
                          ChoiceChip(
                            label: Text(p.label),
                            selected: _priority == p,
                            onSelected: (sel) =>
                                setState(() => _priority = sel ? p : null),
                          ),
                      ],
                    ),
                    Padding(
                      padding: const EdgeInsets.only(top: 6),
                      child: Text(
                        'Not sure? Leave it empty - the biomedical team will decide.',
                        style: theme.textTheme.bodySmall
                            ?.copyWith(color: scheme.onSurfaceVariant),
                      ),
                    ),
                    const SizedBox(height: 20),
                    const _FieldLabel('Photos (optional)'),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: [
                        for (var i = 0; i < _photos.length; i++)
                          _PhotoThumb(
                            path: _photos[i],
                            onRemove: () =>
                                setState(() => _photos.removeAt(i)),
                          ),
                        if (_photos.length < _maxPhotos)
                          _AddPhotoTile(onTap: _addPhoto),
                      ],
                    ),
                    const SizedBox(height: 24),
                    if (_error != null) ...[
                      Container(
                        padding: const EdgeInsets.all(12),
                        decoration: BoxDecoration(
                          color: scheme.errorContainer,
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: Row(
                          children: [
                            Icon(Icons.error_outline,
                                color: scheme.onErrorContainer),
                            const SizedBox(width: 8),
                            Expanded(
                              child: Text(_error!,
                                  style:
                                      TextStyle(color: scheme.onErrorContainer)),
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(height: 12),
                    ],
                    FilledButton.icon(
                      onPressed: _submitting ? null : _submit,
                      icon: _submitting
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child:
                                  CircularProgressIndicator(strokeWidth: 2.5),
                            )
                          : const Icon(Icons.send_outlined),
                      label: Text(_submitting ? 'Sending...' : 'Submit report'),
                    ),
                    const SizedBox(height: 16),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _deviceTile() {
    if (_loadingDevice) {
      return const ListTile(
        leading: SizedBox(
          width: 24,
          height: 24,
          child: CircularProgressIndicator(strokeWidth: 2.5),
        ),
        title: Text('Loading device...'),
      );
    }
    final d = _device;
    if (d != null) {
      return ListTile(
        leading: const Icon(Icons.monitor_heart_outlined),
        title: Text(d.name),
        subtitle: Text('${d.deviceCode} - ${d.department}'),
        trailing: TextButton(onPressed: _pickDevice, child: const Text('Change')),
      );
    }
    return ListTile(
      leading: const Icon(Icons.search),
      title: const Text('Select a device'),
      subtitle: Text(_deviceLoadError ?? 'Choose the device that has a problem'),
      trailing: const Icon(Icons.chevron_right),
      onTap: _pickDevice,
    );
  }
}

class _FieldLabel extends StatelessWidget {
  const _FieldLabel(this.text);
  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Text(text,
          style: Theme.of(context)
              .textTheme
              .titleSmall
              ?.copyWith(fontWeight: FontWeight.w600)),
    );
  }
}

class _AddPhotoTile extends StatelessWidget {
  const _AddPhotoTile({required this.onTap});
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Semantics(
      button: true,
      label: 'Add photo',
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(12),
        child: Container(
          width: 84,
          height: 84,
          decoration: BoxDecoration(
            border: Border.all(color: scheme.outline),
            borderRadius: BorderRadius.circular(12),
          ),
          child: Column(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              Icon(Icons.add_a_photo_outlined, color: scheme.primary),
              const SizedBox(height: 4),
              Text('Add', style: Theme.of(context).textTheme.labelSmall),
            ],
          ),
        ),
      ),
    );
  }
}

class _PhotoThumb extends StatelessWidget {
  const _PhotoThumb({required this.path, required this.onRemove});
  final String path;
  final VoidCallback onRemove;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return SizedBox(
      width: 84,
      height: 84,
      child: Stack(
        fit: StackFit.expand,
        children: [
          ClipRRect(
            borderRadius: BorderRadius.circular(12),
            child: Image.file(
              File(path),
              fit: BoxFit.cover,
              errorBuilder: (_, _, _) => Container(
                color: scheme.surfaceContainerHighest,
                child: const Icon(Icons.broken_image_outlined),
              ),
            ),
          ),
          Positioned(
            top: 2,
            right: 2,
            child: Semantics(
              button: true,
              label: 'Remove photo',
              child: GestureDetector(
                onTap: onRemove,
                child: const CircleAvatar(
                  radius: 12,
                  backgroundColor: Colors.black54,
                  child: Icon(Icons.close, size: 14, color: Colors.white),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _DevicePickerSheet extends StatefulWidget {
  const _DevicePickerSheet();

  @override
  State<_DevicePickerSheet> createState() => _DevicePickerSheetState();
}

class _DevicePickerSheetState extends State<_DevicePickerSheet> {
  late Future<List<Device>> _future;
  String _query = '';

  @override
  void initState() {
    super.initState();
    _load();
  }

  void _load() {
    _future = context.read<DeviceRepository>().listDevices();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: EdgeInsets.only(bottom: MediaQuery.viewInsetsOf(context).bottom),
      child: SizedBox(
        height: MediaQuery.sizeOf(context).height * 0.7,
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
              child: TextField(
                onChanged: (v) => setState(() => _query = v.trim().toLowerCase()),
                decoration: const InputDecoration(
                  hintText: 'Search by name or code',
                  prefixIcon: Icon(Icons.search),
                ),
              ),
            ),
            Expanded(
              child: FutureBuilder<List<Device>>(
                future: _future,
                builder: (context, snap) {
                  if (snap.connectionState != ConnectionState.done) {
                    return const LoadingView(message: 'Loading devices...');
                  }
                  if (snap.hasError) {
                    return ErrorView(
                      message: 'Unable to load devices.',
                      onRetry: () => setState(_load),
                    );
                  }
                  final devices = (snap.data ?? const <Device>[])
                      .where((d) =>
                          _query.isEmpty ||
                          d.name.toLowerCase().contains(_query) ||
                          d.deviceCode.toLowerCase().contains(_query) ||
                          d.department.toLowerCase().contains(_query))
                      .toList();
                  if (devices.isEmpty) {
                    return const EmptyView(
                        message: 'No devices match your search.');
                  }
                  return ListView.builder(
                    itemCount: devices.length,
                    itemBuilder: (context, i) {
                      final d = devices[i];
                      return ListTile(
                        leading: const Icon(Icons.monitor_heart_outlined),
                        title: Text(d.name),
                        subtitle: Text('${d.deviceCode} - ${d.department}'),
                        onTap: () => Navigator.of(context).pop(d),
                      );
                    },
                  );
                },
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _SuccessView extends StatelessWidget {
  const _SuccessView({required this.ticket});
  final Ticket ticket;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 440),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Icon(Icons.check_circle_outline,
                      size: 80, color: theme.colorScheme.primary),
                  const SizedBox(height: 16),
                  Text('Problem reported',
                      textAlign: TextAlign.center,
                      style: theme.textTheme.headlineSmall
                          ?.copyWith(fontWeight: FontWeight.w700)),
                  const SizedBox(height: 8),
                  Text(
                    'Ticket ${ticket.number} was created for '
                    '${ticket.deviceName} (${ticket.deviceCode}).\n'
                    'The biomedical team has been notified.',
                    textAlign: TextAlign.center,
                    style: theme.textTheme.bodyMedium?.copyWith(
                        color: theme.colorScheme.onSurfaceVariant),
                  ),
                  const SizedBox(height: 32),
                  FilledButton(
                    onPressed: () => context.go(AppRoutes.home),
                    child: const Text('Back to Home'),
                  ),
                  const SizedBox(height: 12),
                  OutlinedButton(
                    style: OutlinedButton.styleFrom(
                        minimumSize: const Size.fromHeight(52)),
                    onPressed: () => context.go(AppRoutes.tickets),
                    child: const Text('View my tickets'),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
