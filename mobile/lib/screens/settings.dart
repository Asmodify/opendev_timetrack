import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';

import '../api.dart';
import '../models.dart';
import '../office_watcher.dart';

class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key, required this.me, required this.onChanged, required this.onSignOut});
  final Me me;
  final Future<void> Function() onChanged;
  final Future<void> Function() onSignOut;

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  final _watcher = OfficeWatcher.instance;

  void _toast(String text) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));

  Future<void> _setConsent(bool accept) async {
    try {
      await Api.instance.setConsent(accept);
      if (!accept) await _watcher.stop();
      await widget.onChanged();
    } on ApiError catch (e) {
      _toast(e.message);
    }
  }

  Future<void> _setOfficeCheckIn(bool on) async {
    if (!on) {
      await _watcher.stop();
      setState(() {});
      return;
    }
    final error = await _watcher.start();
    if (error != null) _toast(error);
    setState(() {});
  }

  @override
  Widget build(BuildContext context) {
    final u = widget.me.user;
    final t = Theme.of(context).textTheme;
    return ListView(padding: const EdgeInsets.symmetric(vertical: 8), children: [
      ListTile(
        leading: CircleAvatar(child: Text(u.name.isEmpty ? '?' : u.name[0].toUpperCase())),
        title: Text(u.name),
        subtitle: Text(u.email),
      ),
      const Divider(),
      Padding(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 0),
        child: Text('Automatic tracking', style: t.titleMedium),
      ),
      const Padding(
        padding: EdgeInsets.fromLTRB(16, 8, 16, 8),
        child: Text(
          'When this is on, your hours start when you arrive at an office and stop when you leave. '
          'The phone checks your position on the phone itself and only tells the server "arrived" or "left". '
          'Your location, keystrokes, screens and apps are never sent. You, your manager and HR can see your hours. '
          'You can turn this off at any time and clock in by hand instead.',
        ),
      ),
      SwitchListTile(
        title: const Text('I accept automatic tracking'),
        value: u.consent,
        onChanged: _setConsent,
      ),
      ValueListenableBuilder<bool>(
        valueListenable: _watcher.enabled,
        builder: (context, on, _) => SwitchListTile(
          title: const Text('Check in when I arrive at the office'),
          subtitle: ValueListenableBuilder<String>(
            valueListenable: _watcher.status,
            builder: (context, status, _) => Text(u.consent ? status : 'Accept automatic tracking first.'),
          ),
          value: on,
          onChanged: u.consent ? _setOfficeCheckIn : null,
        ),
      ),
      ValueListenableBuilder<String>(
        valueListenable: _watcher.status,
        builder: (context, status, _) => status.contains('Settings')
            ? ListTile(
                leading: const Icon(Icons.location_on_outlined),
                title: const Text('Open location settings'),
                subtitle: const Text('Choose "Allow all the time" so check-in works with the app closed.'),
                onTap: Geolocator.openAppSettings,
              )
            : const SizedBox.shrink(),
      ),
      const Divider(),
      ListTile(
        leading: const Icon(Icons.logout),
        title: const Text('Sign out'),
        subtitle: const Text('Stops office check-in on this phone'),
        onTap: widget.onSignOut,
      ),
    ]);
  }
}
