import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../api.dart';
import '../models.dart';

/// Time off: the worker's leave balance, their requests, and a form to send a new one.
/// Mirrors Timely's "цагийн хүсэлт": many request types, a manager approves each.
class LeavePage extends StatefulWidget {
  const LeavePage({super.key, required this.me});
  final Me me;

  @override
  State<LeavePage> createState() => _LeavePageState();
}

class _LeavePageState extends State<LeavePage> {
  LeaveBalance? _balance;
  List<LeaveRequest>? _requests;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    try {
      final r = await Api.instance.leave();
      if (mounted) setState(() { _balance = r.balance; _requests = r.requests; _error = null; });
    } on ApiError catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  void _toast(String text) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));

  Future<void> _newRequest() async {
    final sent = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => _LeaveSheet(types: widget.me.leaveTypes),
    );
    if (sent == true) { _toast('Request sent to your manager'); await _load(); }
  }

  Future<void> _cancel(LeaveRequest r) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        title: const Text('Cancel request?'),
        content: Text(r.span),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Keep')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Cancel it')),
        ],
      ),
    );
    if (ok != true) return;
    try { await Api.instance.cancelLeave(r.id); await _load(); } on ApiError catch (e) { _toast(e.message); }
  }

  @override
  Widget build(BuildContext context) {
    final requests = _requests;
    return Scaffold(
      floatingActionButton: FloatingActionButton.extended(
        onPressed: widget.me.leaveTypes.isEmpty ? null : _newRequest,
        icon: const Icon(Icons.add),
        label: const Text('Request'),
      ),
      body: RefreshIndicator(
        onRefresh: _load,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 96),
          children: [
            if (_balance != null) _BalanceCard(balance: _balance!),
            const SizedBox(height: 12),
            Text('My requests', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 4),
            if (_error != null)
              Padding(padding: const EdgeInsets.all(24), child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)))
            else if (requests == null)
              const Padding(padding: EdgeInsets.all(32), child: Center(child: CircularProgressIndicator()))
            else if (requests.isEmpty)
              const Padding(padding: EdgeInsets.all(24), child: Text('No requests yet. Tap Request to ask for leave, a sick day, a day working from home, or overtime.', textAlign: TextAlign.center))
            else
              ...requests.map((r) => _LeaveTile(request: r, onCancel: r.cancellable ? () => _cancel(r) : null)),
          ],
        ),
      ),
    );
  }
}

class _BalanceCard extends StatelessWidget {
  const _BalanceCard({required this.balance});
  final LeaveBalance balance;

  @override
  Widget build(BuildContext context) {
    String d(double v) => v == v.roundToDouble() ? v.toInt().toString() : v.toString();
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text('Annual leave this year', style: Theme.of(context).textTheme.titleSmall),
          const SizedBox(height: 8),
          Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
            _stat(context, d(balance.remaining), 'Left'),
            _stat(context, d(balance.used), 'Used'),
            _stat(context, d(balance.pending), 'Pending'),
            _stat(context, d(balance.entitlement), 'Total'),
          ]),
        ]),
      ),
    );
  }

  Widget _stat(BuildContext context, String value, String label) => Column(children: [
        Text(value, style: Theme.of(context).textTheme.headlineSmall),
        Text(label, style: Theme.of(context).textTheme.bodySmall),
      ]);
}

class _LeaveTile extends StatelessWidget {
  const _LeaveTile({required this.request, this.onCancel});
  final LeaveRequest request;
  final VoidCallback? onCancel;

  static const _colors = {'pending': Colors.orange, 'approved': Colors.green, 'rejected': Colors.red, 'cancelled': Colors.grey};

  @override
  Widget build(BuildContext context) {
    final color = _colors[request.status] ?? Colors.grey;
    return Card(
      child: ListTile(
        title: Text(request.typeLabel, style: const TextStyle(fontWeight: FontWeight.w600)),
        subtitle: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Text(request.span),
          if (request.reason.isNotEmpty) Text(request.reason, style: Theme.of(context).textTheme.bodySmall),
          if (request.reviewerNote.isNotEmpty) Text('Manager: ${request.reviewerNote}', style: Theme.of(context).textTheme.bodySmall),
        ]),
        isThreeLine: request.reason.isNotEmpty || request.reviewerNote.isNotEmpty,
        trailing: Column(mainAxisAlignment: MainAxisAlignment.center, crossAxisAlignment: CrossAxisAlignment.end, children: [
          Chip(
            label: Text(request.status[0].toUpperCase() + request.status.substring(1)),
            side: BorderSide(color: color),
            visualDensity: VisualDensity.compact,
            padding: EdgeInsets.zero,
          ),
          if (onCancel != null) TextButton(onPressed: onCancel, style: TextButton.styleFrom(visualDensity: VisualDensity.compact), child: const Text('Cancel')),
        ]),
      ),
    );
  }
}

class _LeaveSheet extends StatefulWidget {
  const _LeaveSheet({required this.types});
  final List<LeaveType> types;

  @override
  State<_LeaveSheet> createState() => _LeaveSheetState();
}

class _LeaveSheetState extends State<_LeaveSheet> {
  late LeaveType _type = widget.types.first;
  DateTime _start = DateUtils.dateOnly(DateTime.now());
  DateTime _end = DateUtils.dateOnly(DateTime.now());
  bool _halfDay = false;
  final _hours = TextEditingController(text: '2');
  final _reason = TextEditingController();
  bool _sending = false;
  String? _error;

  @override
  void dispose() {
    _hours.dispose();
    _reason.dispose();
    super.dispose();
  }

  Future<void> _pick(bool isStart) async {
    final now = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      initialDate: isStart ? _start : _end,
      firstDate: DateTime(now.year - 1),
      lastDate: DateTime(now.year + 2),
    );
    if (picked == null) return;
    setState(() {
      if (isStart) {
        _start = picked;
        if (_end.isBefore(_start)) _end = _start;
      } else {
        _end = picked.isBefore(_start) ? _start : picked;
      }
    });
  }

  Future<void> _send() async {
    setState(() { _sending = true; _error = null; });
    final body = <String, Object?>{
      'type': _type.key,
      'start_date': _ymd(_start),
      'end_date': _type.hourly ? _ymd(_start) : _ymd(_end),
      'half_day': !_type.hourly && _halfDay,
      'hours': _type.hourly ? (double.tryParse(_hours.text) ?? 0) : 0,
      'reason': _reason.text.trim(),
    };
    try {
      await Api.instance.requestLeave(body);
      if (mounted) Navigator.pop(context, true);
    } on ApiError catch (e) {
      if (mounted) setState(() { _sending = false; _error = e.message; });
    }
  }

  static String _ymd(DateTime d) => '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

  @override
  Widget build(BuildContext context) {
    final fmt = DateFormat.yMMMd();
    return Padding(
      padding: EdgeInsets.fromLTRB(16, 0, 16, MediaQuery.of(context).viewInsets.bottom + 24),
      child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text('Request time off', style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 16),
        DropdownButtonFormField<LeaveType>(
          initialValue: _type,
          decoration: const InputDecoration(labelText: 'Type', border: OutlineInputBorder()),
          items: [for (final t in widget.types) DropdownMenuItem(value: t, child: Text(t.label))],
          onChanged: (t) => setState(() => _type = t ?? _type),
        ),
        const SizedBox(height: 12),
        if (_type.hourly)
          TextField(
            controller: _hours,
            keyboardType: const TextInputType.numberWithOptions(decimal: true),
            decoration: const InputDecoration(labelText: 'Hours', border: OutlineInputBorder()),
          )
        else
          Row(children: [
            Expanded(child: OutlinedButton(onPressed: () => _pick(true), child: Text('From ${fmt.format(_start)}'))),
            const SizedBox(width: 8),
            Expanded(child: OutlinedButton(onPressed: () => _pick(false), child: Text('To ${fmt.format(_end)}'))),
          ]),
        if (!_type.hourly && DateUtils.isSameDay(_start, _end))
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Half day'),
            value: _halfDay,
            onChanged: (v) => setState(() => _halfDay = v),
          ),
        const SizedBox(height: 12),
        TextField(
          controller: _reason,
          maxLength: 500,
          decoration: const InputDecoration(labelText: 'Reason (optional)', border: OutlineInputBorder()),
        ),
        if (_error != null) Padding(
          padding: const EdgeInsets.only(bottom: 8),
          child: Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
        ),
        const SizedBox(height: 4),
        FilledButton(
          onPressed: _sending ? null : _send,
          child: Padding(
            padding: const EdgeInsets.symmetric(vertical: 10),
            child: _sending ? const SizedBox(height: 20, width: 20, child: CircularProgressIndicator(strokeWidth: 2)) : const Text('Send request'),
          ),
        ),
      ]),
    );
  }
}
