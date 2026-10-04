import 'chat_message.dart';

class AiRequest {
  const AiRequest({
    required this.question,
    this.deviceId,
    this.history = const [],
  });

  final String question;

  /// Set when the chat was opened from a device ("Ask AI" on Device Overview).
  final String? deviceId;

  /// Conversation so far (includes the new question as the last message).
  final List<ChatMessage> history;
}

class AiReply {
  const AiReply({required this.text, this.followUps = const []});
  final String text;
  final List<String> followUps;
}

/// UI depends on this interface only.
/// MockAiAssistantService now -> BackendAiAssistantService later
/// (the backend proxies to the separate `ai/` service; the app never talks
/// to an AI provider directly and never holds an AI API key).
abstract class AiAssistantService {
  /// Throws a [Failure] (e.g. NetworkFailure) if the assistant is unreachable.
  Future<AiReply> ask(AiRequest request);
}
