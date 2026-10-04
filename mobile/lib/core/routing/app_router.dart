import 'package:go_router/go_router.dart';

import '../../features/ai_assistant/presentation/ai_assistant_screen.dart';
import '../../features/auth/presentation/auth_controller.dart';
import '../../features/auth/presentation/forgot_password_screen.dart';
import '../../features/auth/presentation/login_screen.dart';
import '../../features/devices/presentation/device_overview_screen.dart';
import '../../features/home/presentation/home_screen.dart';
import '../../features/notifications/presentation/notifications_screen.dart';
import '../../features/profile/presentation/notification_settings_screen.dart';
import '../../features/profile/presentation/profile_screen.dart';
import '../../features/qr_scanner/presentation/qr_scanner_screen.dart';
import '../../features/tickets/presentation/device_tickets_screen.dart';
import '../../features/tickets/presentation/report_problem_screen.dart';
import '../../features/tickets/presentation/ticket_details_screen.dart';
import '../../features/tickets/presentation/tickets_screen.dart';
import '../widgets/main_scaffold.dart';

class AppRoutes {
  AppRoutes._();
  static const login = '/login';
  static const forgotPassword = '/forgot-password';
  static const home = '/home';
  static const tickets = '/tickets';
  static const ai = '/ai';
  static const profile = '/profile';

  /// Full-screen routes (outside the bottom bar), opened with push.
  static const scan = '/scan';
  static const report = '/report';
  static const notifications = '/notifications';
  static const notificationSettings = '/settings/notifications';
  static const assistant = '/assistant';
  static String assistantPath({String? deviceId}) =>
      deviceId == null ? assistant : '$assistant?deviceId=$deviceId';
  static String reportPath({String? deviceId}) =>
      deviceId == null ? report : '$report?deviceId=$deviceId';
  static const device = '/device/:id';
  static String devicePath(String id) => '/device/$id';

  static const deviceTickets = '/device/:id/tickets';
  static String deviceTicketsPath(String id) => '/device/$id/tickets';

  static const ticket = '/ticket/:id';
  static String ticketPath(String id) => '/ticket/$id';
}

GoRouter buildRouter(AuthController auth) {
  return GoRouter(
    initialLocation: AppRoutes.home,
    refreshListenable: auth, // re-runs redirect on login/logout
    redirect: (context, state) {
      final loc = state.matchedLocation;
      final onAuthPage =
          loc == AppRoutes.login || loc == AppRoutes.forgotPassword;
      if (!auth.isAuthenticated) return onAuthPage ? null : AppRoutes.login;
      if (onAuthPage) return AppRoutes.home;
      return null;
    },
    routes: [
      GoRoute(path: AppRoutes.login, builder: (_, _) => const LoginScreen()),
      GoRoute(
        path: AppRoutes.forgotPassword,
        builder: (_, _) => const ForgotPasswordScreen(),
      ),
      GoRoute(path: AppRoutes.scan, builder: (_, _) => const QrScannerScreen()),
      GoRoute(
        path: AppRoutes.report,
        builder: (_, state) => ReportProblemScreen(
          deviceId: state.uri.queryParameters['deviceId'],
        ),
      ),
      GoRoute(
        path: AppRoutes.device,
        builder: (_, state) =>
            DeviceOverviewScreen(deviceId: state.pathParameters['id']!),
      ),
      GoRoute(
        path: AppRoutes.notificationSettings,
        builder: (_, _) => const NotificationSettingsScreen(),
      ),
      GoRoute(
        path: AppRoutes.assistant,
        builder: (_, state) => AiAssistantScreen(
          deviceId: state.uri.queryParameters['deviceId'],
        ),
      ),
      GoRoute(
        path: AppRoutes.notifications,
        builder: (_, _) => const NotificationsScreen(),
      ),
      GoRoute(
        path: AppRoutes.deviceTickets,
        builder: (_, state) =>
            DeviceTicketsScreen(deviceId: state.pathParameters['id']!),
      ),
      GoRoute(
        path: AppRoutes.ticket,
        builder: (_, state) =>
            TicketDetailsScreen(ticketId: state.pathParameters['id']!),
      ),
      // 4 tabs. "Scan" is not a tab: it opens the full-screen scanner.
      StatefulShellRoute.indexedStack(
        builder: (context, state, shell) => MainScaffold(shell: shell),
        branches: [
          StatefulShellBranch(routes: [
            GoRoute(path: AppRoutes.home, builder: (_, _) => const HomeScreen()),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: AppRoutes.tickets, builder: (_, _) => const TicketsScreen()),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: AppRoutes.ai, builder: (_, _) => const AiAssistantScreen()),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(path: AppRoutes.profile, builder: (_, _) => const ProfileScreen()),
          ]),
        ],
      ),
    ],
  );
}
