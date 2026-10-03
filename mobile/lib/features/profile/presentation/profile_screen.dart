import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../auth/presentation/auth_controller.dart';

/// Minimal now (name + logout so we can test the session).
/// Full profile/settings come in Phase 8.
class ProfileScreen extends StatelessWidget {
  const ProfileScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final user = context.watch<AuthController>().user;
    return Scaffold(
      appBar: AppBar(title: const Text('Profile')),
      body: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          ListTile(
            leading: const CircleAvatar(child: Icon(Icons.person)),
            title: Text(user?.fullName ?? ''),
            subtitle: Text(user?.email ?? ''),
          ),
          const Divider(),
          ListTile(
            leading: const Icon(Icons.logout),
            title: const Text('Log out'),
            onTap: () => context.read<AuthController>().logout(),
          ),
        ],
      ),
    );
  }
}
