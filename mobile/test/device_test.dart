import 'package:flutter_test/flutter_test.dart';
import 'package:imedora_mobile/core/errors/failures.dart';
import 'package:imedora_mobile/features/devices/data/mock_device_repository.dart';
import 'package:imedora_mobile/features/devices/domain/device.dart';

Device _deviceWithWarranty(DateTime? expiry) => Device(
      id: 'x',
      deviceCode: 'DEV-X',
      name: 'Test',
      qrIdentifier: 'QR-X',
      manufacturer: 'M',
      model: 'M1',
      category: 'C',
      department: 'D',
      status: DeviceStatus.active,
      criticality: DeviceCriticality.low,
      warrantyExpiry: expiry,
    );

void main() {
  final repo = MockDeviceRepository();

  test('lists the 3 demo devices', () async {
    final list = await repo.listDevices();
    expect(list.map((d) => d.deviceCode), ['DEV-001', 'DEV-002', 'DEV-003']);
  });

  test('IMEDORA-DEV-001 (any case) resolves to DEV-001', () async {
    final d = await repo.getByQrIdentifier('imedora-dev-001');
    expect(d.deviceCode, 'DEV-001');
  });

  test('the real qr_identifier from the DB seed also resolves', () async {
    final d = await repo.getByQrIdentifier('QR-CMC-DEV-002');
    expect(d.name, 'CT Scanner Unit');
  });

  test('unknown QR throws NotFoundFailure', () async {
    expect(() => repo.getByQrIdentifier('NOPE'),
        throwsA(isA<NotFoundFailure>()));
  });

  test('warranty status is computed correctly', () {
    final now = DateTime(2026, 10, 2);
    expect(_deviceWithWarranty(null).warrantyStatus(now: now),
        WarrantyStatus.unknown);
    expect(_deviceWithWarranty(DateTime(2026, 9, 1)).warrantyStatus(now: now),
        WarrantyStatus.expired);
    expect(_deviceWithWarranty(DateTime(2026, 11, 1)).warrantyStatus(now: now),
        WarrantyStatus.expiringSoon);
    expect(_deviceWithWarranty(DateTime(2028, 1, 1)).warrantyStatus(now: now),
        WarrantyStatus.active);
  });
}
