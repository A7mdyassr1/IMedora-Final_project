String _two(int n) => n.toString().padLeft(2, '0');

/// 2026-10-02
String formatDate(DateTime d) {
  final l = d.toLocal();
  return '${l.year}-${_two(l.month)}-${_two(l.day)}';
}

/// 2026-10-02 14:05
String formatDateTime(DateTime d) {
  final l = d.toLocal();
  return '${formatDate(l)} ${_two(l.hour)}:${_two(l.minute)}';
}
