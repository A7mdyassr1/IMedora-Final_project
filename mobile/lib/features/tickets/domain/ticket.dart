// Mirrors the IMedora `maintenance_tickets` table (+ names the backend
// resolves from devices / ticket updates).
//
// DB NOTES (schema is frozen, so we adapt here):
// - There is NO category column: the category is stored as a prefix of
//   `problem_description`, e.g. "[Power issue] The device won't turn on".
//   See ProblemDescription below.
// - There is NO ticket-updates table: `updates` is built by the backend
//   from audit_logs / ticket_assignments.
// - `priority` defaults to 'medium' in the DB when not sent.
// - organization_id / hospital_id / reported_by come from the auth token on
//   the backend, so the mobile app only sends device + description + priority.

enum TicketPriority { low, medium, high, critical }

enum TicketStatus {
  open,
  assigned,
  inProgress,
  waitingForParts,
  resolved,
  closed,
  cancelled,
}

enum ProblemCategory {
  notWorking,
  abnormalReading,
  physicalDamage,
  alarm,
  powerIssue,
  other,
}

extension TicketPriorityX on TicketPriority {
  String get label => switch (this) {
        TicketPriority.low => 'Low',
        TicketPriority.medium => 'Medium',
        TicketPriority.high => 'High',
        TicketPriority.critical => 'Critical',
      };
}

extension TicketStatusX on TicketStatus {
  String get label => switch (this) {
        TicketStatus.open => 'Open',
        TicketStatus.assigned => 'Assigned',
        TicketStatus.inProgress => 'In Progress',
        TicketStatus.waitingForParts => 'Waiting for Parts',
        TicketStatus.resolved => 'Resolved',
        TicketStatus.closed => 'Closed',
        TicketStatus.cancelled => 'Cancelled',
      };
}

extension ProblemCategoryX on ProblemCategory {
  String get label => switch (this) {
        ProblemCategory.notWorking => 'Device not working',
        ProblemCategory.abnormalReading => 'Abnormal reading',
        ProblemCategory.physicalDamage => 'Physical damage',
        ProblemCategory.alarm => 'Alarm/problem',
        ProblemCategory.powerIssue => 'Power issue',
        ProblemCategory.other => 'Other',
      };
}

/// Packs/unpacks the category into the single `problem_description` column.
class ProblemDescription {
  ProblemDescription._();

  static String compose(ProblemCategory category, String description) =>
      '[${category.label}] ${description.trim()}';

  static (ProblemCategory, String) parse(String stored) {
    final text = stored.trim();
    final m = RegExp(r'^\[(.+?)\]\s*([\s\S]*)$').firstMatch(text);
    if (m != null) {
      final label = m.group(1)!;
      for (final c in ProblemCategory.values) {
        if (c.label == label) return (c, m.group(2)!.trim());
      }
    }
    return (ProblemCategory.other, text);
  }
}

/// One line of ticket history.
class TicketUpdate {
  const TicketUpdate({
    required this.status,
    required this.message,
    required this.at,
  });
  final TicketStatus status;
  final String message;
  final DateTime at;
}

/// Mirrors `attachments` (always attached to a ticket from the mobile app).
/// In the mock, [fileUrl] holds the local file path of the picked photo.
class TicketAttachment {
  const TicketAttachment({
    required this.id,
    required this.fileName,
    required this.fileUrl,
  });
  final String id;
  final String fileName;
  final String fileUrl;
}

class Ticket {
  const Ticket({
    required this.id,
    required this.number,
    required this.deviceId,
    required this.deviceName,
    required this.deviceCode,
    required this.category,
    required this.description,
    required this.priority,
    required this.status,
    required this.createdAt,
    this.resolvedAt,
    this.updates = const [],
    this.attachments = const [],
  });

  final String id; // UUID
  final String number; // short display id, e.g. TKT-1004
  final String deviceId;
  final String deviceName;
  final String deviceCode;
  final ProblemCategory category;
  final String description;
  final TicketPriority priority;
  final TicketStatus status;
  final DateTime createdAt;
  final DateTime? resolvedAt;
  final List<TicketUpdate> updates;
  final List<TicketAttachment> attachments;
}

/// What the mobile app sends when reporting a problem
/// (later: POST /tickets, photos uploaded separately).
class NewTicketRequest {
  const NewTicketRequest({
    required this.deviceId,
    required this.category,
    required this.description,
    this.priority,
    this.attachmentPaths = const [],
  });
  final String deviceId;
  final ProblemCategory category;
  final String description;
  final TicketPriority? priority; // null -> backend default (medium)
  final List<String> attachmentPaths;
}
