import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import 'package:provider/provider.dart';

import '../../../core/errors/failures.dart';
import '../../../core/routing/app_router.dart';
import '../../devices/domain/device_repository.dart';

/// Full-screen scanner (pushed on top of the tabs, so the camera only runs
/// while this screen is open).
///
/// Flow: scan QR -> DeviceRepository.getByQrIdentifier -> Device Overview.
/// Later the repository calls GET /devices/{qr_identifier}.
class QrScannerScreen extends StatefulWidget {
  const QrScannerScreen({super.key});

  @override
  State<QrScannerScreen> createState() => _QrScannerScreenState();
}

class _QrScannerScreenState extends State<QrScannerScreen> {
  final MobileScannerController _controller = MobileScannerController(
    formats: const [BarcodeFormat.qrCode],
    detectionSpeed: DetectionSpeed.noDuplicates,
  );
  final TextEditingController _codeCtrl = TextEditingController();

  bool _busy = false;
  bool _torchOn = false;
  String? _error;
  String? _lastFailedCode;
  DateTime? _lastFailedAt;

  @override
  void dispose() {
    _controller.dispose();
    _codeCtrl.dispose();
    super.dispose();
  }

  Future<void> _lookup(String raw) async {
    final code = raw.trim();
    if (code.isEmpty || _busy) return;
    FocusScope.of(context).unfocus();
    setState(() {
      _busy = true;
      _error = null;
    });
    final repo = context.read<DeviceRepository>();
    try {
      final device = await repo.getByQrIdentifier(code);
      if (!mounted) return;
      // Replace the scanner so "back" from the device returns to the tabs.
      context.pushReplacement(AppRoutes.devicePath(device.id));
    } on Failure catch (f) {
      _fail(code, f.message);
    } catch (_) {
      _fail(code, 'Unable to load device information.');
    }
  }

  void _fail(String code, String message) {
    if (!mounted) return;
    setState(() {
      _busy = false;
      _error = message;
      _lastFailedCode = code;
      _lastFailedAt = DateTime.now();
    });
  }

  void _onDetect(BarcodeCapture capture) {
    if (_busy) return;
    String? raw;
    for (final b in capture.barcodes) {
      final v = b.rawValue;
      if (v != null && v.trim().isNotEmpty) {
        raw = v;
        break;
      }
    }
    if (raw == null) return;

    // Don't hammer the lookup with the same bad code while it's in view.
    final failedAt = _lastFailedAt;
    final recentlyFailed = raw == _lastFailedCode &&
        failedAt != null &&
        DateTime.now().difference(failedAt) < const Duration(seconds: 3);
    if (recentlyFailed) return;

    _codeCtrl.text = raw;
    _lookup(raw);
  }

  Future<void> _toggleTorch() async {
    try {
      await _controller.toggleTorch();
      if (mounted) setState(() => _torchOn = !_torchOn);
    } catch (_) {
      // Device has no torch (e.g. emulator) - ignore.
    }
  }

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Scan Device'),
        actions: [
          IconButton(
            tooltip: 'Flashlight',
            icon: Icon(_torchOn ? Icons.flash_on : Icons.flash_off),
            onPressed: _toggleTorch,
          ),
        ],
      ),
      body: Column(
        children: [
          Expanded(
            child: Stack(
              fit: StackFit.expand,
              children: [
                MobileScanner(controller: _controller, onDetect: _onDetect),
                IgnorePointer(
                  child: Center(
                    child: Container(
                      width: 240,
                      height: 240,
                      decoration: BoxDecoration(
                        border: Border.all(color: Colors.white, width: 3),
                        borderRadius: BorderRadius.circular(20),
                      ),
                    ),
                  ),
                ),
                Positioned(
                  left: 16,
                  right: 16,
                  bottom: 16,
                  child: Center(
                    child: Container(
                      padding: const EdgeInsets.symmetric(
                          horizontal: 14, vertical: 8),
                      decoration: BoxDecoration(
                        color: Colors.black54,
                        borderRadius: BorderRadius.circular(20),
                      ),
                      child: const Text(
                        'Point the camera at the device QR code',
                        style: TextStyle(color: Colors.white),
                      ),
                    ),
                  ),
                ),
                if (_busy)
                  Container(
                    color: Colors.black54,
                    child: const Center(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          CircularProgressIndicator(),
                          SizedBox(height: 16),
                          Text('Looking up device...',
                              style: TextStyle(color: Colors.white)),
                        ],
                      ),
                    ),
                  ),
              ],
            ),
          ),
          Material(
            color: scheme.surfaceContainer,
            child: SafeArea(
              top: false,
              child: Center(
                child: ConstrainedBox(
                  constraints: const BoxConstraints(maxWidth: 560),
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        if (_error != null) ...[
                          Container(
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(
                              color: scheme.errorContainer,
                              borderRadius: BorderRadius.circular(12),
                            ),
                            child: Row(
                              children: [
                                Icon(Icons.error_outline,
                                    color: scheme.onErrorContainer),
                                const SizedBox(width: 8),
                                Expanded(
                                  child: Text(_error!,
                                      style: TextStyle(
                                          color: scheme.onErrorContainer)),
                                ),
                              ],
                            ),
                          ),
                          const SizedBox(height: 12),
                        ],
                        TextField(
                          controller: _codeCtrl,
                          textInputAction: TextInputAction.search,
                          textCapitalization: TextCapitalization.characters,
                          onSubmitted: _lookup,
                          decoration: const InputDecoration(
                            labelText: 'Or enter the device code',
                            hintText: 'e.g. IMEDORA-DEV-001',
                            prefixIcon: Icon(Icons.keyboard_outlined),
                          ),
                        ),
                        const SizedBox(height: 12),
                        FilledButton.icon(
                          icon: const Icon(Icons.search),
                          label: const Text('Find device'),
                          onPressed:
                              _busy ? null : () => _lookup(_codeCtrl.text),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
