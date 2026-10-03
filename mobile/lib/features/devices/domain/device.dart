// Mirrors the IMedora `devices` table (+ names resolved from
// device_models / manufacturers / departments / locations by the backend).
// Only the fields a doctor/nurse needs - no biomedical-engineering internals.

enum DeviceStatus { active, underMaintenance, outOfService, decommissioned }

enum DeviceCriticality { low, medium, high, critical }

enum WarrantyStatus { active, expiringSoon, expired, unknown }

extension DeviceStatusX on DeviceStatus {
  /// Plain-language label for hospital staff.
  String get label => switch (this) {
        DeviceStatus.active => 'Operational',
        DeviceStatus.underMaintenance => 'Under maintenance',
        DeviceStatus.outOfService => 'Out of service',
        DeviceStatus.decommissioned => 'Decommissioned',
      };
}

extension DeviceCriticalityX on DeviceCriticality {
  String get label => switch (this) {
        DeviceCriticality.low => 'Low',
        DeviceCriticality.medium => 'Medium',
        DeviceCriticality.high => 'High',
        DeviceCriticality.critical => 'Critical',
      };
}

extension WarrantyStatusX on WarrantyStatus {
  String get label => switch (this) {
        WarrantyStatus.active => 'Under warranty',
        WarrantyStatus.expiringSoon => 'Expires soon',
        WarrantyStatus.expired => 'Expired',
        WarrantyStatus.unknown => 'Unknown',
      };
}

class Device {
  const Device({
    required this.id,
    required this.deviceCode,
    required this.name,
    required this.qrIdentifier,
    required this.manufacturer,
    required this.model,
    required this.category,
    required this.department,
    required this.status,
    required this.criticality,
    this.location,
    this.installationDate,
    this.warrantyExpiry,
  });

  /// UUID. Use this for navigation - device_code is only unique per hospital.
  final String id;
  final String deviceCode; // e.g. DEV-001
  final String name;
  final String qrIdentifier; // globally unique
  final String manufacturer;
  final String model;
  final String category;
  final String department;
  final String? location; // "Building - Floor - Room"
  final DeviceStatus status;
  final DeviceCriticality criticality;
  final DateTime? installationDate;
  final DateTime? warrantyExpiry;

  /// Computed on the device: the DB only stores warranty_expiry.
  /// "Expiring soon" = 90 days or less remaining.
  WarrantyStatus warrantyStatus({DateTime? now}) {
    final expiry = warrantyExpiry;
    if (expiry == null) return WarrantyStatus.unknown;
    final today = _dateOnly(now ?? DateTime.now());
    final exp = _dateOnly(expiry);
    if (exp.isBefore(today)) return WarrantyStatus.expired;
    if (exp.difference(today).inDays <= 90) return WarrantyStatus.expiringSoon;
    return WarrantyStatus.active;
  }

  static DateTime _dateOnly(DateTime d) => DateTime(d.year, d.month, d.day);
}
