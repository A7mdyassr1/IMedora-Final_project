import '../../../core/errors/failures.dart';
import '../domain/device.dart';
import '../domain/device_repository.dart';

class MockDeviceRepository implements DeviceRepository {
  MockDeviceRepository() : _devices = _buildDevices();

  final List<Device> _devices;

  /// Extra QR values accepted by the mock (task spec uses IMEDORA-DEV-001).
  static const _aliases = {
    'IMEDORA-DEV-001': 'DEV-001',
    'IMEDORA-DEV-002': 'DEV-002',
    'IMEDORA-DEV-003': 'DEV-003',
  };

  static List<Device> _buildDevices() {
    final now = DateTime.now();
    return [
      Device(
        id: '22222222-2222-2222-2222-000000000001',
        deviceCode: 'DEV-001',
        name: 'Philips Ventilator',
        qrIdentifier: 'QR-CMC-DEV-001',
        manufacturer: 'Philips',
        model: 'Efficia CM10',
        category: 'Ventilator',
        department: 'ICU',
        location: 'Main Building - Floor 2 - Room 204',
        status: DeviceStatus.active,
        criticality: DeviceCriticality.critical,
        installationDate: DateTime(2024, 3, 10),
        warrantyExpiry: now.add(const Duration(days: 400)),
      ),
      Device(
        id: '22222222-2222-2222-2222-000000000002',
        deviceCode: 'DEV-002',
        name: 'CT Scanner Unit',
        qrIdentifier: 'QR-CMC-DEV-002',
        manufacturer: 'GE Healthcare',
        model: 'Revolution CT',
        category: 'CT Scanner',
        department: 'Radiology',
        location: 'Main Building - Floor 1 - Room 101',
        status: DeviceStatus.active,
        criticality: DeviceCriticality.high,
        installationDate: DateTime(2023, 1, 15),
        warrantyExpiry: DateTime(2028, 1, 15),
      ),
      Device(
        id: '22222222-2222-2222-2222-000000000003',
        deviceCode: 'DEV-003',
        name: 'Dialysis Machine',
        qrIdentifier: 'QR-CMC-DEV-003',
        manufacturer: 'Fresenius Medical Care',
        model: '5008S',
        category: 'Dialysis Machine',
        department: 'Dialysis',
        location: 'East Wing - Floor 3 - Room 310',
        status: DeviceStatus.underMaintenance,
        criticality: DeviceCriticality.critical,
        installationDate: DateTime(2022, 6, 20),
        warrantyExpiry: now.add(const Duration(days: 45)),
      ),
    ];
  }

  Future<void> _latency() =>
      Future<void>.delayed(const Duration(milliseconds: 400));

  @override
  Future<Device> getByQrIdentifier(String qrIdentifier) async {
    await _latency();
    final code = qrIdentifier.trim().toUpperCase();
    final aliasCode = _aliases[code];
    for (final d in _devices) {
      if (d.qrIdentifier.toUpperCase() == code || d.deviceCode == aliasCode) {
        return d;
      }
    }
    throw const NotFoundFailure('No device found for this code.');
  }

  @override
  Future<Device> getById(String id) async {
    await _latency();
    for (final d in _devices) {
      if (d.id == id) return d;
    }
    throw const NotFoundFailure('Device not found.');
  }

  @override
  Future<List<Device>> listDevices() async {
    await _latency();
    return List.unmodifiable(_devices);
  }
}
