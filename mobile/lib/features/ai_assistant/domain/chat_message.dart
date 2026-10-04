enum ChatRole { user, assistant }

class ChatMessage {
  const ChatMessage({
    required this.id,
    required this.role,
    required this.text,
    required this.createdAt,
    this.followUps = const [],
  });

  final String id;
  final ChatRole role;
  final String text;
  final DateTime createdAt;

  /// Suggested next questions (assistant messages only).
  final List<String> followUps;
}
