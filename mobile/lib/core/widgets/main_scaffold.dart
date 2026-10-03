import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';

import '../routing/app_router.dart';

class _Dest {
  const _Dest(this.label, this.icon, this.selectedIcon);
  final String label;
  final IconData icon;
  final IconData selectedIcon;
}

// 5 visual destinations. Scan (index 1) is an ACTION, not a tab: it pushes the
// full-screen scanner, so the shell only has 4 branches (home/tickets/ai/profile).
const _destinations = [
  _Dest('Home', Icons.home_outlined, Icons.home),
  _Dest('Scan', Icons.qr_code_scanner, Icons.qr_code_scanner),
  _Dest('Tickets', Icons.confirmation_number_outlined, Icons.confirmation_number),
  _Dest('AI', Icons.smart_toy_outlined, Icons.smart_toy),
  _Dest('Profile', Icons.person_outline, Icons.person),
];

const int _scanIndex = 1;

int _branchToDest(int branch) => branch < _scanIndex ? branch : branch + 1;
int _destToBranch(int dest) => dest < _scanIndex ? dest : dest - 1;

/// App shell: bottom bar on phones, NavigationRail on tablets.
class MainScaffold extends StatelessWidget {
  const MainScaffold({super.key, required this.shell});
  final StatefulNavigationShell shell;

  void _onTap(BuildContext context, int destIndex) {
    if (destIndex == _scanIndex) {
      context.push(AppRoutes.scan);
      return;
    }
    final branch = _destToBranch(destIndex);
    shell.goBranch(branch, initialLocation: branch == shell.currentIndex);
  }

  @override
  Widget build(BuildContext context) {
    final wide = MediaQuery.sizeOf(context).width >= 720;
    final selected = _branchToDest(shell.currentIndex);

    if (wide) {
      return Scaffold(
        body: Row(
          children: [
            NavigationRail(
              selectedIndex: selected,
              onDestinationSelected: (i) => _onTap(context, i),
              labelType: NavigationRailLabelType.all,
              destinations: [
                for (final d in _destinations)
                  NavigationRailDestination(
                    icon: Icon(d.icon),
                    selectedIcon: Icon(d.selectedIcon),
                    label: Text(d.label),
                  ),
              ],
            ),
            const VerticalDivider(width: 1),
            Expanded(child: shell),
          ],
        ),
      );
    }

    return Scaffold(
      body: shell,
      bottomNavigationBar:
          _BottomBar(current: selected, onTap: (i) => _onTap(context, i)),
    );
  }
}

class _BottomBar extends StatelessWidget {
  const _BottomBar({required this.current, required this.onTap});
  final int current;
  final ValueChanged<int> onTap;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Material(
      color: scheme.surfaceContainer,
      elevation: 3,
      child: SafeArea(
        top: false,
        child: SizedBox(
          height: 72,
          child: Row(
            children: [
              for (var i = 0; i < _destinations.length; i++)
                Expanded(
                  child: i == _scanIndex
                      ? _ScanButton(
                          label: _destinations[i].label,
                          onTap: () => onTap(i),
                        )
                      : _NavItem(
                          dest: _destinations[i],
                          selected: current == i,
                          onTap: () => onTap(i),
                        ),
                ),
            ],
          ),
        ),
      ),
    );
  }
}

class _NavItem extends StatelessWidget {
  const _NavItem({required this.dest, required this.selected, required this.onTap});
  final _Dest dest;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    final color = selected ? scheme.primary : scheme.onSurfaceVariant;
    return Semantics(
      button: true,
      selected: selected,
      label: dest.label,
      child: InkWell(
        onTap: onTap,
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(selected ? dest.selectedIcon : dest.icon, color: color),
            const SizedBox(height: 4),
            Text(dest.label,
                style: Theme.of(context)
                    .textTheme
                    .labelSmall
                    ?.copyWith(color: color)),
          ],
        ),
      ),
    );
  }
}

class _ScanButton extends StatelessWidget {
  const _ScanButton({required this.label, required this.onTap});
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final scheme = Theme.of(context).colorScheme;
    return Semantics(
      button: true,
      label: 'Scan device',
      child: InkWell(
        onTap: onTap,
        child: Column(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Material(
              color: scheme.primary,
              shape: const CircleBorder(),
              elevation: 4,
              child: SizedBox(
                width: 46,
                height: 46,
                child: Icon(Icons.qr_code_scanner,
                    color: scheme.onPrimary, size: 26),
              ),
            ),
            const SizedBox(height: 4),
            Text(label,
                style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color: scheme.primary, fontWeight: FontWeight.w600)),
          ],
        ),
      ),
    );
  }
}
