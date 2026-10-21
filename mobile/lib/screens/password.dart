import 'package:flutter/material.dart';

import '../api.dart';

class PasswordScreen extends StatefulWidget {
  const PasswordScreen({super.key, required this.onDone});
  final Future<void> Function() onDone;

  @override
  State<PasswordScreen> createState() => _PasswordScreenState();
}

class _PasswordScreenState extends State<PasswordScreen> {
  final _current = TextEditingController();
  final _next = TextEditingController();
  String? _error;

  Future<void> _save() async {
    if (_next.text.length < 8) {
      setState(() => _error = 'Use at least 8 characters.');
      return;
    }
    try {
      await Api.instance.changePassword(_current.text, _next.text);
      await widget.onDone();
    } on ApiError catch (e) {
      setState(() => _error = e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Choose your password')),
      body: ListView(padding: const EdgeInsets.all(24), children: [
        const Text('You signed in with a temporary password. Pick your own to continue.'),
        const SizedBox(height: 16),
        TextField(controller: _current, obscureText: true, decoration: const InputDecoration(labelText: 'Temporary password')),
        const SizedBox(height: 12),
        TextField(controller: _next, obscureText: true, decoration: const InputDecoration(labelText: 'New password (8+ characters)')),
        if (_error != null) ...[
          const SizedBox(height: 12),
          Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
        ],
        const SizedBox(height: 20),
        FilledButton(onPressed: _save, child: const Text('Save password')),
      ]),
    );
  }
}
