import 'package:flutter_test/flutter_test.dart';
import 'package:imedora_mobile/core/errors/failures.dart';
import 'package:imedora_mobile/features/ai_assistant/data/mock_ai_assistant_service.dart';
import 'package:imedora_mobile/features/ai_assistant/domain/ai_assistant_service.dart';
import 'package:imedora_mobile/features/ai_assistant/domain/chat_message.dart';
import 'package:imedora_mobile/features/ai_assistant/presentation/ai_chat_controller.dart';
import 'package:imedora_mobile/features/devices/data/mock_device_repository.dart';
import 'package:imedora_mobile/features/tickets/data/mock_ticket_repository.dart';

const _dev1 = '22222222-2222-2222-2222-000000000001';

class _FlakyService implements AiAssistantService {
  int calls = 0;
  @override
  Future<AiReply> ask(AiRequest request) async {
    calls++;
    if (calls == 1) throw const NetworkFailure();
    return const AiReply(text: 'ok');
  }
}

void main() {
  late MockAiAssistantService service;

  setUp(() {
    final devices = MockDeviceRepository();
    service = MockAiAssistantService(devices, MockTicketRepository(devices));
  });

  Future<String> reply(String q, {String? deviceId}) async =>
      (await service.ask(AiRequest(question: q, deviceId: deviceId))).text;

  group('MockAiAssistantService', () {
    test('status with device context', () async {
      final t = await reply('What is the status of this device?', deviceId: _dev1);
      expect(t, contains('Philips Ventilator'));
      expect(t, contains('operational'));
    });

    test('last service comes from resolved tickets', () async {
      final t = await reply('When was this device last serviced?', deviceId: _dev1);
      expect(t, contains('TKT-1001'));
      expect(t, contains('Pressure sensor recalibrated'));
    });

    test('asks which device when none is known', () async {
      final t = await reply('What is the status of this device?');
      expect(t, contains('Which device'));
    });

    test('a device code in the question is enough', () async {
      final t = await reply('status of DEV-003?');
      expect(t, contains('Dialysis Machine'));
      expect(t, contains('under maintenance'));
    });

    test('how to report a problem', () async {
      expect(await reply('How can I report a problem?'), contains('Report Problem'));
    });

    test('device stops working: safety first, backup device', () async {
      final t = await reply('What should I do if the device stops working?');
      expect(t, contains('backup device'));
    });

    test('clinical questions are declined', () async {
      expect(await reply('What dose should I give?'), contains("can't help with clinical"));
    });

    test('"test error" throws NetworkFailure', () async {
      expect(() => reply('test error'), throwsA(isA<NetworkFailure>()));
    });
  });

  group('AiChatController', () {
    test('starts with a welcome message, then adds question and answer', () async {
      final c = AiChatController(service);
      expect(c.messages.length, 1);
      expect(c.messages.first.followUps, isNotEmpty);
      final future = c.ask('hello');
      expect(c.isLoading, isTrue);
      await future;
      expect(c.isLoading, isFalse);
      expect(c.messages.length, 3);
      expect(c.messages[1].role, ChatRole.user);
      expect(c.messages[2].role, ChatRole.assistant);
      c.dispose();
    });

    test('an error is kept and retry re-sends without duplicating the question', () async {
      final c = AiChatController(_FlakyService());
      await c.ask('hi');
      expect(c.error, isNotNull);
      expect(c.messages.length, 2);
      await c.retry();
      expect(c.error, isNull);
      expect(c.messages.length, 3);
      expect(c.messages.last.text, 'ok');
      c.dispose();
    });

    test('reset starts a new chat', () async {
      final c = AiChatController(service);
      await c.ask('hello');
      c.reset();
      expect(c.messages.length, 1);
      c.dispose();
    });

    test('empty input is ignored', () async {
      final c = AiChatController(service);
      await c.ask('   ');
      expect(c.messages.length, 1);
      c.dispose();
    });
  });
}
