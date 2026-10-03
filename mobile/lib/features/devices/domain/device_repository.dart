import 'device.dart';

/// UI depends on this interface only.
/// Mock now -> ApiDeviceRepository (GET /devices/{qr_identifier}) later.
abstract class DeviceRepository {
  /// Resolves a scanned QR value. Throws [NotFoundFailure] if unknown.
  Future<Device> getByQrIdentifier(String qrIdentifier);

  /// Throws [NotFoundFailure] if unknown.
  Future<Device> getById(String id);

  Future<List<Device>> listDevices();
}
