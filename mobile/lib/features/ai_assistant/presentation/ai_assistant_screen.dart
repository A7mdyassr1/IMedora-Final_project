import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../devices/domain/device.dart';
import '../../devices/domain/device_repository.dart';
import '../domain/ai_assistant_service.dart';
import '../domain/chat_message.dart';
import 'ai_chat_controller.dart';

/// Used twice: as the "AI" tab (general chat) and, via /assistant?deviceId=...,
/// as a full-screen chat about one device ("Ask AI" on Device Overview).
class AiAssistantScreen extends StatefulWidget {
  const AiAssistantScreen({super.key, this.deviceId});
  final String? deviceId;

  @override
  State<AiAssistantScreen> createState() => _AiAssistantScreenState();
}

class _AiAssistantScreenState extends State<AiAssistantScreen> {
  late final AiChatController _chat;
  final _inputCtrl = TextEditingController();
  final _scroll = ScrollController();
  Device? _device;

  @override
  void initState() {
    super.initState();
    _chat = AiChatController(
      context.read<AiAssistantService>(),
      deviceId: widget.deviceId,
    )..addListener(_scrollToBottom);
    final id = widget.deviceId;
    if (id != null) _loadDevice(id);
  }

  @override
  void dispose() {
    _chat
      ..removeListener(_scrollToBottom)
      ..dispose();
    _inputCtrl.dispose();
    _scroll.dispose();
    super.dispose();
  }

  Future<void> _loadDevice(String id) async {
    final repo = context.read<DeviceRepository>();
    try {
      final d = await repo.getById(id);
      if (mounted) setState(() => _device = d);
    } catch (_) {
      // The chat still works without the context chip.
    }
  }

  void _scrollToBottom() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted || !_scroll.hasClients) return;
      _scroll.animateTo(
        _scroll.position.maxScrollExtent,
        duration: const Duration(milliseconds: 250),
        curve: Curves.easeOut,
      );
    });
  }

  void _send() {
    final text = _inputCtrl.text;
    if (text.trim().isEmpty || _chat.isLoading) return;
    _inputCtrl.clear();
    _chat.ask(text);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(widget.deviceId != null ? 'Ask AI' : 'AI Assistant'),
        actions: [
          IconButton(
            tooltip: 'New chat',
            icon: const Icon(Icons.refresh),
            onPressed: _chat.reset,
          ),
        ],
      ),
      body: ListenableBuilder(
        listenable: _chat,
        builder: (context, _) {
          final messages = _chat.messages;
          final last = messages.last;
          final showFollowUps = last.role == ChatRole.assistant &&
              !_chat.isLoading &&
              _chat.error == null &&
              last.followUps.isNotEmpty;

          return Column(
            children: [
              Expanded(
                child: Align(
                  alignment: Alignment.topCenter,
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 720),
                    child: ListView(
                      controller: _scroll,
                      padding: const EdgeInsets.all(16),
                      children: [
                        const _DisclaimerBanner(),
                        if (_device != null) _DeviceChip(device: _device!),
                        for (final m in messages) _MessageBubble(message: m),
                        if (showFollowUps)
                          _FollowUps(
                            questions: last.followUps,
                            onTap: _chat.ask,
                          ),
                        if (_chat.isLoading) const _TypingBubble(),
                        if (_chat.error != null)
                          _ErrorBubble(
                            message: _chat.error!,
                            onRetry: _chat.retry,
                          ),
                      ],
                    ),
                  ),
                ),
              ),
              _InputBar(
                controller: _inputCtrl,
                busy: _chat.isLoading,
                onSend: _send,
              ),
            ],
          );
        },
      ),
    );
  }
}

class _DisclaimerBanner extends StatelessWidget {
  const _DisclaimerBanner();

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Card(
      color: scheme.secondaryContainer,
      child: Padding(
        padding: const EdgeInsets.all(12),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(Icons.info_outline, size: 20, color: scheme.onSecondaryContainer),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                "Informational only. I can't replace biomedical engineers or "
                "technicians. In an emergency, follow your hospital's procedures.",
                style: Theme.of(context)
                    .textTheme
                    .bodySmall
                    ?.copyWith(color: scheme.onSecondaryContainer),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _DeviceChip extends StatelessWidget {
  const _DeviceChip({required this.device});
  final Device device;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Align(
        alignment: Alignment.centerLeft,
        child: Chip(
          avatar: const Icon(Icons.monitor_heart_outlined, size: 18),
          label: Text('About: ${device.name} (${device.deviceCode})'),
        ),
      ),
    );
  }
}

class _AssistantAvatar extends StatelessWidget {
  const _AssistantAvatar();

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return CircleAvatar(
      radius: 16,
      backgroundColor: scheme.primaryContainer,
      child: Icon(Icons.smart_toy_outlined,
          size: 18, color: scheme.onPrimaryContainer),
    );
  }
}

class _MessageBubble extends StatelessWidget {
  const _MessageBubble({required this.message});
  final ChatMessage message;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final isUser = message.role == ChatRole.user;
    final bg = isUser ? scheme.primary : scheme.surfaceContainerHigh;
    final fg = isUser ? scheme.onPrimary : scheme.onSurface;

    return Semantics(
      label: '${isUser ? 'You' : 'Assistant'}: ${message.text}',
      child: ExcludeSemantics(
        child: Padding(
          padding: const EdgeInsets.symmetric(vertical: 6),
          child: Row(
            mainAxisAlignment:
                isUser ? MainAxisAlignment.end : MainAxisAlignment.start,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (!isUser) ...[const _AssistantAvatar(), const SizedBox(width: 8)],
              Flexible(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 520),
                  child: Container(
                    padding:
                        const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                    decoration: BoxDecoration(
                      color: bg,
                      borderRadius: BorderRadius.only(
                        topLeft: const Radius.circular(16),
                        topRight: const Radius.circular(16),
                        bottomLeft: Radius.circular(isUser ? 16 : 4),
                        bottomRight: Radius.circular(isUser ? 4 : 16),
                      ),
                    ),
                    child: Text(message.text, style: TextStyle(color: fg)),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _FollowUps extends StatelessWidget {
  const _FollowUps({required this.questions, required this.onTap});
  final List<String> questions;
  final void Function(String) onTap;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(left: 40, top: 6, bottom: 6),
      child: Wrap(
        spacing: 8,
        runSpacing: 8,
        children: [
          for (final q in questions)
            ActionChip(label: Text(q), onPressed: () => onTap(q)),
        ],
      ),
    );
  }
}

class _TypingBubble extends StatelessWidget {
  const _TypingBubble();

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Semantics(
      label: 'Assistant is typing',
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Row(
          children: [
            const _AssistantAvatar(),
            const SizedBox(width: 8),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              decoration: BoxDecoration(
                color: scheme.surfaceContainerHigh,
                borderRadius: BorderRadius.circular(16),
              ),
              child: const Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  SizedBox(
                    width: 16,
                    height: 16,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                  SizedBox(width: 10),
                  Text('Thinking...'),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ErrorBubble extends StatelessWidget {
  const _ErrorBubble({required this.message, required this.onRetry});
  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 6),
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: scheme.errorContainer,
          borderRadius: BorderRadius.circular(12),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(Icons.error_outline, color: scheme.onErrorContainer),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(message,
                      style: TextStyle(color: scheme.onErrorContainer)),
                ),
              ],
            ),
            TextButton.icon(
              onPressed: onRetry,
              icon: const Icon(Icons.refresh),
              label: const Text('Try again'),
            ),
          ],
        ),
      ),
    );
  }
}

class _InputBar extends StatelessWidget {
  const _InputBar({
    required this.controller,
    required this.busy,
    required this.onSend,
  });
  final TextEditingController controller;
  final bool busy;
  final VoidCallback onSend;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Material(
      color: theme.colorScheme.surfaceContainer,
      child: SafeArea(
        top: false,
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 720),
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 10, 12, 8),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      Expanded(
                        child: TextField(
                          controller: controller,
                          minLines: 1,
                          maxLines: 4,
                          textInputAction: TextInputAction.send,
                          textCapitalization: TextCapitalization.sentences,
                          onSubmitted: (_) => onSend(),
                          decoration: const InputDecoration(
                            hintText: 'Ask a question...',
                          ),
                        ),
                      ),
                      const SizedBox(width: 8),
                      ValueListenableBuilder<TextEditingValue>(
                        valueListenable: controller,
                        builder: (context, value, _) => IconButton.filled(
                          tooltip: 'Send',
                          onPressed: (busy || value.text.trim().isEmpty)
                              ? null
                              : onSend,
                          icon: const Icon(Icons.send),
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  Text(
                    'Informational only. Not a replacement for biomedical engineers.',
                    textAlign: TextAlign.center,
                    style: theme.textTheme.bodySmall
                        ?.copyWith(color: theme.colorScheme.onSurfaceVariant),
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
