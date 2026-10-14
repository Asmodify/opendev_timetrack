import 'package:flutter/material.dart';

import '../api.dart';
import '../models.dart';
import 'password.dart';
import 'settings.dart';
import 'today.dart';
import 'week.dart';

class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key, required this.onSignedOut});
  final Future<void> Function() onSignedOut;

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> with WidgetsBindingObserver {
  int _tab = 0;
  Me? _me;
  List<Project> _projects = [];
  String? _error;
  int _refresh = 0;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    _load();
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) _load();
  }

  Future<void> _load() async {
    try {
      final results = await Future.wait([Api.instance.me(), Api.instance.projects()]);
      if (!mounted) return;
      setState(() {
        _me = results[0] as Me;
        _projects = results[1] as List<Project>;
        _error = null;
        _refresh++;
      });
    } on ApiError catch (e) {
      if (e.status == 401) {
        await widget.onSignedOut();
        return;
      }
      if (mounted) setState(() => _error = e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final me = _me;
    if (me == null) {
      return Scaffold(
        body: Center(
          child: _error == null
              ? const CircularProgressIndicator()
              : Padding(
                  padding: const EdgeInsets.all(24),
                  child: Column(mainAxisSize: MainAxisSize.min, children: [
                    Text(_error!, textAlign: TextAlign.center),
                    const SizedBox(height: 12),
                    FilledButton(onPressed: _load, child: const Text('Try again')),
                    TextButton(onPressed: widget.onSignedOut, child: const Text('Sign out')),
                  ]),
                ),
        ),
      );
    }
    if (me.user.mustChangePassword) {
      return PasswordScreen(onDone: _load);
    }
    final pages = [
      TodayPage(key: ValueKey('today$_refresh'), me: me, projects: _projects, onChanged: _load),
      WeekPage(key: ValueKey('week$_refresh'), me: me),
      SettingsPage(me: me, onChanged: _load, onSignOut: widget.onSignedOut),
    ];
    return Scaffold(
      appBar: AppBar(title: Text(me.company), centerTitle: false),
      body: pages[_tab],
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.today_outlined), selectedIcon: Icon(Icons.today), label: 'Day'),
          NavigationDestination(icon: Icon(Icons.bar_chart_outlined), selectedIcon: Icon(Icons.bar_chart), label: 'Week'),
          NavigationDestination(icon: Icon(Icons.settings_outlined), selectedIcon: Icon(Icons.settings), label: 'Settings'),
        ],
      ),
    );
  }
}
