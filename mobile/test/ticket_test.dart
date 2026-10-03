import 'package:flutter_test/flutter_test.dart';
import 'package:imedora_mobile/core/errors/failures.dart';
import 'package:imedora_mobile/features/devices/data/mock_device_repository.dart';
import 'package:imedora_mobile/features/tickets/data/mock_ticket_repository.dart';
import 'package:imedora_mobile/features/tickets/domain/ticket.dart';

const _dev1 = '22222222-2222-2222-2222-000000000001';

MockTicketRepository _repo() => MockTicketRepository(MockDeviceRepository());

void main() {
  test('category is packed into / read from problem_description', () {
    final stored =
        ProblemDescription.compose(ProblemCategory.powerIssue, ' No power ');
    expect(stored, '[Power issue] No power');
    final (cat, text) = ProblemDescription.parse(stored);
    expect(cat, ProblemCategory.powerIssue);
    expect(text, 'No power');
  });

  test('plain text without a known prefix parses as "other"', () {
    final (cat, text) = ProblemDescription.parse('Screen is flickering');
    expect(cat, ProblemCategory.other);
    expect(text, 'Screen is flickering');
  });

  test('createTicket returns an open ticket, medium priority by default',
      () async {
    final repo = _repo();
    final t = await repo.createTicket(const NewTicketRequest(
      deviceId: _dev1,
      category: ProblemCategory.notWorking,
      description: 'Will not turn on at all',
    ));
    expect(t.status, TicketStatus.open);
    expect(t.priority, TicketPriority.medium);
    expect(t.deviceCode, 'DEV-001');
    expect(t.updates, isNotEmpty);
  });

  test('a created ticket appears first in getMyTickets', () async {
    final repo = _repo();
    final t = await repo.createTicket(const NewTicketRequest(
      deviceId: _dev1,
      category: ProblemCategory.alarm,
      description: 'Alarm keeps going off',
      priority: TicketPriority.high,
    ));
    final list = await repo.getMyTickets();
    expect(list.first.id, t.id);
    expect(list.first.priority, TicketPriority.high);
  });

  test('createTicket with an unknown device throws NotFoundFailure', () async {
    final repo = _repo();
    expect(
      () => repo.createTicket(const NewTicketRequest(
        deviceId: 'nope',
        category: ProblemCategory.other,
        description: 'Something is wrong here',
      )),
      throwsA(isA<NotFoundFailure>()),
    );
  });
}
