import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:imedora_mobile/features/auth/data/mock_auth_repository.dart';
import 'package:imedora_mobile/features/auth/presentation/auth_controller.dart';
import 'package:imedora_mobile/features/profile/domain/role_label.dart';
import 'package:imedora_mobile/features/profile/presentation/profile_screen.dart';
import 'package:imedora_mobile/features/profile/presentation/settings_controller.dart';
import 'package:provider/provider.dart';

import 'test_fakes.dart';

void main() {
  test('roleLabel gives friendly names', () {
    expect(roleLabel('department_user'), 'Hospital staff');
    expect(roleLabel('biomedical_engineer'), 'Biomedical Engineer');
    expect(roleLabel('admin'), 'Administrator');
    expect(roleLabel('some_new_role'), 'Some new role');
  });

  testWidgets('Profile shows the user and logs out after confirmation',
      (tester) async {
    tester.view.physicalSize = const Size(900, 2400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    final auth = AuthController(MockAuthRepository(), MemoryTokenStorage());
    await tester.runAsync(() => auth.login('demo', 'Demo123!'));
    expect(auth.isAuthenticated, isTrue);

    await tester.pumpWidget(
      MultiProvider(
        providers: [
          ChangeNotifierProvider<AuthController>.value(value: auth),
          ChangeNotifierProvider<SettingsController>(
            create: (_) => SettingsController(MemorySettingsRepository()),
          ),
        ],
        child: const MaterialApp(home: ProfileScreen()),
      ),
    );

    expect(find.text('Dr. Sara Ahmed'), findsOneWidget);
    expect(find.text('demo@imedora.local'), findsOneWidget);
    expect(find.text('Cairo Medical Center - Main Campus'), findsOneWidget);
    expect(find.text('ICU'), findsOneWidget);
    expect(find.text('Hospital staff'), findsOneWidget);

    // Cancel keeps the session.
    await tester.tap(find.text('Log out'));
    await tester.pumpAndSettle();
    expect(find.text('Log out?'), findsOneWidget);
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(auth.isAuthenticated, isTrue);

    // Confirm logs out.
    await tester.tap(find.text('Log out'));
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(FilledButton, 'Log out'));
    await tester.pumpAndSettle();
    expect(auth.isAuthenticated, isFalse);
  });
}
