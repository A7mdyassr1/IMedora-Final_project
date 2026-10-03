import 'package:flutter/material.dart';

/// Temporary screen body for features built in later phases.
class PhasePlaceholder extends StatelessWidget {
  const PhasePlaceholder({
    super.key,
    required this.title,
    required this.icon,
    required this.phase,
    this.children = const [],
  });

  final String title;
  final IconData icon;
  final String phase;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    return Scaffold(
      appBar: AppBar(title: Text(title)),
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 480),
          child: Padding(
            padding: const EdgeInsets.all(24),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(icon, size: 64, color: theme.colorScheme.primary),
                const SizedBox(height: 16),
                Text(title, style: theme.textTheme.headlineSmall),
                const SizedBox(height: 8),
                Text('Coming in $phase',
                    style: theme.textTheme.bodyMedium
                        ?.copyWith(color: theme.colorScheme.onSurfaceVariant)),
                ...children,
              ],
            ),
          ),
        ),
      ),
    );
  }
}
