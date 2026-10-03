import 'package:flutter/material.dart';

import '../../../core/widgets/phase_placeholder.dart';

class AiAssistantScreen extends StatelessWidget {
  const AiAssistantScreen({super.key});

  @override
  Widget build(BuildContext context) => const PhasePlaceholder(
        title: 'AI Assistant',
        icon: Icons.smart_toy_outlined,
        phase: 'Phase 7',
      );
}
