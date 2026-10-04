import 'package:flutter/foundation.dart';

import '../../../core/errors/failures.dart';
import '../domain/ai_assistant_service.dart';
import '../domain/chat_message.dart';

/// State of ONE chat (the AI tab has one; "Ask AI" from a device opens another).
class AiChatController extends ChangeNotifier {
  AiChatController(this._service, {this.deviceId}) {
    _messages.add(_welcome());
  }

  final AiAssistantService _service;
  final String? deviceId;

  final List<ChatMessage> _messages = [];
  bool _loading = false;
  String? _error;
  String? _failedQuestion;
  int _counter = 0;
  int _session = 0;
  bool _disposed = false;

  List<ChatMessage> get messages => List.unmodifiable(_messages);
  bool get isLoading => _loading;
  String? get error => _error;

  static const _deviceQuestions = [
    'What is the status of this device?',
    'When was this device last serviced?',
    'How can I report a problem?',
    'What should I do if the device stops working?',
  ];

  static const _generalQuestions = [
    'How can I report a problem?',
    'What should I do if the device stops working?',
    'What is the status of DEV-001?',
    'What is the status of my tickets?',
  ];

  ChatMessage _welcome() => ChatMessage(
        id: 'm${++_counter}',
        role: ChatRole.assistant,
        text: deviceId != null
            ? 'Hi! Ask me about this device: its status, service history, or what to do if something goes wrong.'
            : "Hi! I'm the IMedora assistant. I can answer simple questions about devices, tickets and how to use this app.",
        createdAt: DateTime.now(),
        followUps: deviceId != null ? _deviceQuestions : _generalQuestions,
      );

  Future<void> ask(String text) async {
    final q = text.trim();
    if (q.isEmpty || _loading) return;
    _messages.add(ChatMessage(
      id: 'm${++_counter}',
      role: ChatRole.user,
      text: q,
      createdAt: DateTime.now(),
    ));
    _error = null;
    _failedQuestion = null;
    await _send(q);
  }

  /// Re-sends the question that failed (without adding it to the chat again).
  Future<void> retry() async {
    final q = _failedQuestion;
    if (q == null || _loading) return;
    _error = null;
    _failedQuestion = null;
    await _send(q);
  }

  Future<void> _send(String q) async {
    final session = _session;
    _loading = true;
    _notify();
    try {
      final reply = await _service.ask(AiRequest(
        question: q,
        deviceId: deviceId,
        history: List.unmodifiable(_messages),
      ));
      if (_disposed || session != _session) return;
      _messages.add(ChatMessage(
        id: 'm${++_counter}',
        role: ChatRole.assistant,
        text: reply.text,
        createdAt: DateTime.now(),
        followUps: reply.followUps,
      ));
    } on Failure catch (f) {
      if (_disposed || session != _session) return;
      _error = f.message;
      _failedQuestion = q;
    } catch (_) {
      if (_disposed || session != _session) return;
      _error = 'Something went wrong. Please try again.';
      _failedQuestion = q;
    }
    _loading = false;
    _notify();
  }

  /// "New chat".
  void reset() {
    _session++;
    _messages
      ..clear()
      ..add(_welcome());
    _loading = false;
    _error = null;
    _failedQuestion = null;
    _notify();
  }

  void _notify() {
    if (!_disposed) notifyListeners();
  }

  @override
  void dispose() {
    _disposed = true;
    super.dispose();
  }
}
