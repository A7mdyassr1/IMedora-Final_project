import '../../../core/errors/failures.dart';
import '../../../core/utils/date_format.dart';
import '../../devices/domain/device.dart';
import '../../devices/domain/device_repository.dart';
import '../../tickets/domain/ticket.dart';
import '../../tickets/domain/ticket_repository.dart';
import '../domain/ai_assistant_service.dart';

/// Rule-based fake assistant: answers from the mock devices/tickets so the
/// whole chat UI can be built and tested before the real AI service exists.
///
/// Tip for testing the error state: ask anything containing "test error".
class MockAiAssistantService implements AiAssistantService {
  MockAiAssistantService(this._devices, this._tickets);

  final DeviceRepository _devices;
  final TicketRepository _tickets;

  static const _statusQ = 'What is the status of this device?';
  static const _serviceQ = 'When was this device last serviced?';
  static const _reportQ = 'How can I report a problem?';
  static const _stopsQ = 'What should I do if the device stops working?';

  static const _defaultFollowUps = [_reportQ, _stopsQ];

  @override
  Future<AiReply> ask(AiRequest request) async {
    await Future<void>.delayed(const Duration(milliseconds: 900));
    final q = request.question.trim().toLowerCase();

    if (q.contains('test error')) {
      throw const NetworkFailure('The assistant is not reachable right now.');
    }
    if (_has(q, ['dose', 'dosage', 'diagnos', 'prescri', 'treatment', 'medication', 'symptom'])) {
      return const AiReply(
        text: "I can't help with clinical or treatment questions. Please ask a "
            "clinician or follow your hospital's clinical guidelines.\n\n"
            'I can help with device status, service history, and reporting problems.',
        followUps: _defaultFollowUps,
      );
    }
    if (_has(q, ['how can i report', 'how do i report', 'report a problem', 'report an issue'])) {
      return const AiReply(
        text: 'To report a problem:\n'
            '1. Scan the device QR code (or open the device from Scan).\n'
            '2. Tap Report Problem.\n'
            "3. Choose what's wrong and describe it. Add a photo if it helps.\n"
            '4. Tap Submit report.\n\n'
            "You'll get a ticket number and can follow its progress in My Tickets.",
        followUps: [_stopsQ, 'What is the status of my tickets?'],
      );
    }
    if (_has(q, ['stops working', 'stopped working', 'stop working', 'not working', 'broken'])) {
      return const AiReply(
        text: 'If a device stops working:\n'
            '1. Patient safety comes first. If the device is connected to a '
            "patient, follow your department's emergency procedure and switch "
            'to a backup device.\n'
            "2. Don't open or try to repair it.\n"
            '3. Note any alarm or message on the screen.\n'
            '4. Report the problem here with the details (choose High or '
            'Critical priority if patients are affected).\n'
            '5. For urgent failures, also call your biomedical engineering team directly.',
        followUps: [_reportQ],
      );
    }
    if (q.contains('ticket')) return _ticketsSummary();
    if (_has(q, ['last serviced', 'last service', 'serviced', 'maintenance history'])) {
      return _lastService(request);
    }
    if (_has(q, ['status', 'condition', 'operational', 'warranty'])) {
      return _deviceStatus(request);
    }
    if (RegExp(r'^(hi|hello|hey)\b').hasMatch(q)) {
      return const AiReply(
        text: "Hello! I'm the IMedora assistant. I can answer simple questions "
            "about devices and tickets. I don't replace biomedical engineers or technicians.",
        followUps: _defaultFollowUps,
      );
    }
    return const AiReply(
      text: "I'm not sure about that yet. I can help with device status, "
          'service history, how to report a problem, and what to do if a device '
          'stops working.\n\nFor technical issues, please report a problem so '
          'the biomedical team can help.',
      followUps: _defaultFollowUps,
    );
  }

  bool _has(String q, List<String> keys) => keys.any(q.contains);

  bool _isActive(Ticket t) =>
      t.status != TicketStatus.resolved &&
      t.status != TicketStatus.closed &&
      t.status != TicketStatus.cancelled;

  /// The device from the chat context, or one named in the question ("DEV-002").
  Future<Device?> _resolveDevice(AiRequest r) async {
    try {
      final id = r.deviceId;
      if (id != null) return await _devices.getById(id);
      final m = RegExp(r'dev-\d{3}', caseSensitive: false).firstMatch(r.question);
      if (m != null) {
        final code = m.group(0)!.toUpperCase();
        for (final d in await _devices.listDevices()) {
          if (d.deviceCode == code) return d;
        }
      }
    } on Failure {
      return null;
    }
    return null;
  }

  AiReply get _needDevice => const AiReply(
        text: 'Which device do you mean? Scan its QR code and tap "Ask AI" on '
            'the device page, or mention its code (for example DEV-001).',
        followUps: ['What is the status of DEV-001?', _reportQ],
      );

  Future<AiReply> _deviceStatus(AiRequest r) async {
    final d = await _resolveDevice(r);
    if (d == null) return _needDevice;

    final tickets = await _tickets.getTicketsForDevice(d.id);
    final active = tickets.where(_isActive).toList();
    final expiry = d.warrantyExpiry;

    final b = StringBuffer()
      ..writeln('${d.name} (${d.deviceCode}) in ${d.department} is currently '
          '${d.status.label.toLowerCase()}.')
      ..writeln('Criticality: ${d.criticality.label}.')
      ..writeln('Warranty: ${d.warrantyStatus().label}'
          '${expiry != null ? ' (until ${formatDate(expiry)})' : ''}.');
    if (active.isEmpty) {
      b.write('There are no active tickets for this device.');
    } else {
      b.write('Active tickets: '
          '${active.map((t) => '${t.number} (${t.status.label})').join(', ')}.');
    }
    if (d.status == DeviceStatus.underMaintenance ||
        d.status == DeviceStatus.outOfService) {
      b.write('\n\nThis device may be unavailable. Please use an alternative device if you need one.');
    }
    return AiReply(text: b.toString(), followUps: const [_serviceQ, _reportQ]);
  }

  Future<AiReply> _lastService(AiRequest r) async {
    final d = await _resolveDevice(r);
    if (d == null) return _needDevice;

    final done = (await _tickets.getTicketsForDevice(d.id))
        .where((t) => t.status == TicketStatus.resolved || t.status == TicketStatus.closed)
        .toList()
      ..sort((a, b) => (b.resolvedAt ?? b.createdAt).compareTo(a.resolvedAt ?? a.createdAt));

    if (done.isEmpty) {
      return AiReply(
        text: "I can't see a completed service for ${d.name} (${d.deviceCode}) in "
            'the ticket history available to me. The biomedical team keeps the full maintenance records.',
        followUps: const [_statusQ, _reportQ],
      );
    }
    final t = done.first;
    final updates = [...t.updates]..sort((a, b) => a.at.compareTo(b.at));
    final detail = updates.isNotEmpty ? updates.last.message : t.description;
    return AiReply(
      text: 'The most recent completed service I can see for ${d.name} '
          '(${d.deviceCode}) was ticket ${t.number}, resolved on '
          '${formatDate(t.resolvedAt ?? t.createdAt)}:\n$detail',
      followUps: const [_statusQ, _reportQ],
    );
  }

  Future<AiReply> _ticketsSummary() async {
    final all = await _tickets.getMyTickets();
    if (all.isEmpty) {
      return const AiReply(
        text: "You haven't reported any tickets yet.",
        followUps: [_reportQ],
      );
    }
    final active = all.where(_isActive).toList();
    final b = StringBuffer('You have ${all.length} ticket${all.length == 1 ? '' : 's'}: '
        '${active.length} active and ${all.length - active.length} completed.');
    for (final t in active.take(3)) {
      b.write('\n- ${t.number} ${t.deviceName}: ${t.status.label}');
    }
    b.write('\n\nOpen the Tickets tab for details.');
    return AiReply(text: b.toString(), followUps: const [_reportQ, _stopsQ]);
  }
}
