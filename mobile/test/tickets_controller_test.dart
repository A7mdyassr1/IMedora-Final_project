import 'package:flutter_test/flutter_test.dart';
import 'package:imedora_mobile/core/storage/token_storage.dart';
import 'package:imedora_mobile/features/auth/data/mock_auth_repository.dart';
import 'package:imedora_mobile/features/auth/presentation/auth_controller.dart';
import 'package:imedora_mobile/features/devices/data/mock_device_repository.dart';
import 'package:imedora_mobile/features/tickets/data/mock_ticket_repository.dart';
import 'package:imedora_mobile/features/tickets/domain/ticket.dart';
import 'package:imedora_mobile/features/tickets/presentation/tickets_controller.dart';

const _dev1 = '22222222-2222-2222-2222-000000000001';
const _dev3 = '22222222-2222-2222-2222-000000000003';

class _MemoryTokenStorage implements TokenStorage {
  String? token;
  @override
  Future<String?> read() async => token;
  @override
  Future<void> write(String t) async => token = t;
  @override
  Future<void> clear() async => token = null;
}

void main() {
  late MockTicketRepository repo;
  late AuthController auth;
  late TicketsController controller;

  setUp(() {
    repo = MockTicketRepository(MockDeviceRepository());
    auth = AuthController(MockAuthRepository(), _MemoryTokenStorage());
    controller = TicketsController(repo, auth);
  });

  tearDown(() => controller.dispose());

  test('starts idle, then loads the 3 demo tickets (newest first)', () async {
    expect(controller.status, LoadStatus.idle);
    await controller.load();
    expect(controller.status, LoadStatus.loaded);
    expect(controller.tickets.map((t) => t.number),
        ['TKT-1003', 'TKT-1002', 'TKT-1001']);
  });

  test('a silent reload picks up a newly created ticket', () async {
    await controller.load();
    await repo.createTicket(const NewTicketRequest(
      deviceId: _dev1,
      category: ProblemCategory.powerIssue,
      description: 'No power since this morning',
    ));
    await controller.load(silent: true);
    expect(controller.tickets.length, 4);
    expect(controller.tickets.first.number, 'TKT-1004');
  });

  test('getTicketsForDevice returns only that device\'s tickets', () async {
    final list = await repo.getTicketsForDevice(_dev3);
    expect(list.length, 1);
    expect(list.single.deviceCode, 'DEV-003');
  });

  test('logging out resets the tickets state', () async {
    await auth.login('demo', 'Demo123!');
    await controller.load();
    expect(controller.status, LoadStatus.loaded);
    await auth.logout();
    expect(controller.status, LoadStatus.idle);
    expect(controller.tickets, isEmpty);
  });
}
