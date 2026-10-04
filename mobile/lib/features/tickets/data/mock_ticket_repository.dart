import '../../../core/errors/failures.dart';
import '../../devices/domain/device_repository.dart';
import '../domain/ticket.dart';
import '../domain/ticket_repository.dart';

/// In-memory tickets (lost when the app restarts - it's a mock).
class MockTicketRepository implements TicketRepository {
  MockTicketRepository(this._devices, {this.onTicketCreated}) {
    _seed();
  }

  final DeviceRepository _devices;

  /// Mock-only hook: the real backend creates the notification itself.
  final void Function(Ticket ticket)? onTicketCreated;
  final List<Ticket> _tickets = [];
  int _counter = 1003;

  // Same ids as MockDeviceRepository.
  static const _dev1 = '22222222-2222-2222-2222-000000000001';
  static const _dev2 = '22222222-2222-2222-2222-000000000002';
  static const _dev3 = '22222222-2222-2222-2222-000000000003';

  void _seed() {
    final now = DateTime.now();
    DateTime ago(int days) => now.subtract(Duration(days: days));

    _tickets.addAll([
      Ticket(
        id: 'ticket-1001',
        number: 'TKT-1001',
        deviceId: _dev1,
        deviceName: 'Philips Ventilator',
        deviceCode: 'DEV-001',
        category: ProblemCategory.abnormalReading,
        description: 'Abnormal pressure reading on the display.',
        priority: TicketPriority.high,
        status: TicketStatus.resolved,
        createdAt: ago(10),
        resolvedAt: ago(9),
        updates: [
          TicketUpdate(
              status: TicketStatus.open,
              message: 'Ticket created.',
              at: ago(10)),
          TicketUpdate(
              status: TicketStatus.assigned,
              message: 'Assigned to a biomedical technician.',
              at: ago(10)),
          TicketUpdate(
              status: TicketStatus.inProgress,
              message: 'Technician started working on the device.',
              at: ago(9)),
          TicketUpdate(
              status: TicketStatus.resolved,
              message: 'Pressure sensor recalibrated and tubing replaced.',
              at: ago(9)),
        ],
      ),
      Ticket(
        id: 'ticket-1002',
        number: 'TKT-1002',
        deviceId: _dev2,
        deviceName: 'CT Scanner Unit',
        deviceCode: 'DEV-002',
        category: ProblemCategory.alarm,
        description: 'Alarm sounds repeatedly during startup.',
        priority: TicketPriority.medium,
        status: TicketStatus.inProgress,
        createdAt: ago(2),
        updates: [
          TicketUpdate(
              status: TicketStatus.open,
              message: 'Ticket created.',
              at: ago(2)),
          TicketUpdate(
              status: TicketStatus.assigned,
              message: 'Assigned to a biomedical technician.',
              at: ago(2)),
          TicketUpdate(
              status: TicketStatus.inProgress,
              message: 'Technician is inspecting the device.',
              at: ago(1)),
        ],
      ),
      Ticket(
        id: 'ticket-1003',
        number: 'TKT-1003',
        deviceId: _dev3,
        deviceName: 'Dialysis Machine',
        deviceCode: 'DEV-003',
        category: ProblemCategory.notWorking,
        description: 'Machine will not power on after cleaning.',
        priority: TicketPriority.critical,
        status: TicketStatus.waitingForParts,
        createdAt: ago(1),
        updates: [
          TicketUpdate(
              status: TicketStatus.open,
              message: 'Ticket created.',
              at: ago(1)),
          TicketUpdate(
              status: TicketStatus.waitingForParts,
              message: 'Waiting for a replacement power supply.',
              at: now.subtract(const Duration(hours: 5))),
        ],
      ),
    ]);
  }

  @override
  Future<Ticket> createTicket(NewTicketRequest request) async {
    await Future<void>.delayed(const Duration(milliseconds: 600));
    // Throws NotFoundFailure for an unknown device, like the backend would.
    final device = await _devices.getById(request.deviceId);

    final now = DateTime.now();
    _counter++;
    final id = 'ticket-$_counter';

    final ticket = Ticket(
      id: id,
      number: 'TKT-$_counter',
      deviceId: device.id,
      deviceName: device.name,
      deviceCode: device.deviceCode,
      category: request.category,
      description: request.description.trim(),
      priority: request.priority ?? TicketPriority.medium,
      status: TicketStatus.open,
      createdAt: now,
      updates: [
        TicketUpdate(
          status: TicketStatus.open,
          message: 'Ticket created. The biomedical team has been notified.',
          at: now,
        ),
      ],
      attachments: [
        for (var i = 0; i < request.attachmentPaths.length; i++)
          TicketAttachment(
            id: '$id-att-$i',
            fileName: request.attachmentPaths[i].split(RegExp(r'[\\/]')).last,
            fileUrl: request.attachmentPaths[i],
          ),
      ],
    );
    _tickets.insert(0, ticket);
    onTicketCreated?.call(ticket);
    return ticket;
  }

  @override
  Future<List<Ticket>> getMyTickets() async {
    await Future<void>.delayed(const Duration(milliseconds: 400));
    final sorted = [..._tickets]
      ..sort((a, b) => b.createdAt.compareTo(a.createdAt));
    return List.unmodifiable(sorted);
  }

  @override
  Future<List<Ticket>> getTicketsForDevice(String deviceId) async {
    await Future<void>.delayed(const Duration(milliseconds: 400));
    final list = _tickets.where((t) => t.deviceId == deviceId).toList()
      ..sort((a, b) => b.createdAt.compareTo(a.createdAt));
    return List.unmodifiable(list);
  }

  @override
  Future<Ticket> getTicketById(String id) async {
    await Future<void>.delayed(const Duration(milliseconds: 300));
    for (final t in _tickets) {
      if (t.id == id) return t;
    }
    throw const NotFoundFailure('Ticket not found.');
  }
}
