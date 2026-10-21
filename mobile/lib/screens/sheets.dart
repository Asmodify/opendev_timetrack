import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../api.dart';
import '../models.dart';

/// Tag a session with a project, add a note, confirm it, or ask for a time change.
class EntrySheet extends StatefulWidget {
  const EntrySheet({super.key, required this.entry, required this.projects});
  final Entry entry;
  final List<Project> projects;

  @override
  State<EntrySheet> createState() => _EntrySheetState();
}

class _EntrySheetState extends State<EntrySheet> {
  late int? _project = widget.entry.project?.id;
  late final _note = TextEditingController(text: widget.entry.note);
  String? _error;

  Future<void> _save({bool confirm = false}) async {
    try {
      await Api.instance.updateEntry(
        widget.entry.id,
        projectId: _project,
        clearProject: _project == null,
        note: _note.text,
        confirmed: confirm ? true : null,
      );
      if (mounted) Navigator.pop(context, true);
    } on ApiError catch (e) {
      setState(() => _error = e.message);
    }
  }

  Future<void> _askChange() async {
    final sent = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => CorrectionSheet(day: widget.entry.start, entry: widget.entry),
    );
    if (sent == true && mounted) Navigator.pop(context, true);
  }

  @override
  Widget build(BuildContext context) {
    final e = widget.entry;
    final end = e.end;
    return Padding(
      padding: EdgeInsets.fromLTRB(20, 0, 20, 20 + MediaQuery.viewInsetsOf(context).bottom),
      child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text('${DateFormat.Hm().format(e.start)} – ${end == null ? 'now' : DateFormat.Hm().format(end)}',
            style: Theme.of(context).textTheme.headlineSmall),
        Text('${hm(e.workedSeconds)} · ${e.location == 'office' ? 'Office' : 'Remote'} · ${e.sourceLabel}'
            '${e.isDraft ? ' · Draft' : ''}'),
        const SizedBox(height: 16),
        DropdownButtonFormField<int?>(
          initialValue: _project,
          decoration: const InputDecoration(labelText: 'Project'),
          items: [
            const DropdownMenuItem<int?>(value: null, child: Text('No project')),
            for (final p in widget.projects)
              DropdownMenuItem<int?>(
                value: p.id,
                child: Row(children: [
                  Icon(Icons.circle, size: 12, color: p.color),
                  const SizedBox(width: 8),
                  Text(p.client == null ? p.name : '${p.name} · ${p.client}'),
                ]),
              ),
          ],
          onChanged: (v) => setState(() => _project = v),
        ),
        const SizedBox(height: 12),
        TextField(controller: _note, maxLength: 300, decoration: const InputDecoration(labelText: 'What did you work on?')),
        if (_error != null) Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
        const SizedBox(height: 8),
        if (e.isDraft)
          FilledButton(onPressed: () => _save(confirm: true), child: const Text('Save and confirm'))
        else
          FilledButton(onPressed: _save, child: const Text('Save')),
        if (!e.running) TextButton(onPressed: _askChange, child: const Text('Times are wrong? Ask for a change')),
      ]),
    );
  }
}

/// Ask a manager to add hours, change an entry's times, or remove it.
class CorrectionSheet extends StatefulWidget {
  const CorrectionSheet({super.key, required this.day, this.entry});
  final DateTime day;
  final Entry? entry;

  @override
  State<CorrectionSheet> createState() => _CorrectionSheetState();
}

class _CorrectionSheetState extends State<CorrectionSheet> {
  late DateTime _date = DateUtils.dateOnly(widget.day);
  late TimeOfDay _start = widget.entry != null ? TimeOfDay.fromDateTime(widget.entry!.start) : const TimeOfDay(hour: 9, minute: 0);
  late TimeOfDay _end = widget.entry?.end != null ? TimeOfDay.fromDateTime(widget.entry!.end!) : const TimeOfDay(hour: 18, minute: 0);
  late int _break = widget.entry?.breakMinutes ?? 60;
  late String _location = widget.entry?.location ?? 'office';
  bool _remove = false;
  final _reason = TextEditingController();
  String? _error;

  Future<void> _send() async {
    if (_reason.text.trim().length < 3) {
      setState(() => _error = 'Say briefly why, so your manager can approve it.');
      return;
    }
    final start = DateTime(_date.year, _date.month, _date.day, _start.hour, _start.minute);
    var end = DateTime(_date.year, _date.month, _date.day, _end.hour, _end.minute);
    if (!end.isAfter(start)) end = end.add(const Duration(days: 1)); // past midnight
    final kind = widget.entry == null ? 'add' : (_remove ? 'delete' : 'edit');
    try {
      await Api.instance.requestCorrection({
        'kind': kind,
        'entry_id': widget.entry?.id,
        'reason': _reason.text.trim(),
        if (kind != 'delete') ...{
          'start': start.toUtc().toIso8601String(),
          'end': end.toUtc().toIso8601String(),
          'break_minutes': _break,
          'location': _location,
        },
      });
      if (mounted) Navigator.pop(context, true);
    } on ApiError catch (e) {
      setState(() => _error = e.message);
    }
  }

  Future<void> _pickTime(bool start) async {
    final t = await showTimePicker(context: context, initialTime: start ? _start : _end);
    if (t != null) setState(() => start ? _start = t : _end = t);
  }

  @override
  Widget build(BuildContext context) {
    final editing = widget.entry != null;
    return Padding(
      padding: EdgeInsets.fromLTRB(20, 0, 20, 20 + MediaQuery.viewInsetsOf(context).bottom),
      child: SingleChildScrollView(
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Text(editing ? 'Ask for a change' : 'Add hours you forgot', style: Theme.of(context).textTheme.titleLarge),
          const Text('Your manager approves the request before it counts.'),
          const SizedBox(height: 12),
          if (editing)
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              value: _remove,
              onChanged: (v) => setState(() => _remove = v),
              title: const Text('Remove this session instead'),
            ),
          if (!_remove) ...[
            ListTile(
              contentPadding: EdgeInsets.zero,
              leading: const Icon(Icons.event),
              title: Text(DateFormat.yMMMEd().format(_date)),
              onTap: editing
                  ? null
                  : () async {
                      final d = await showDatePicker(
                          context: context, initialDate: _date, firstDate: DateTime(2020), lastDate: DateTime.now());
                      if (d != null) setState(() => _date = d);
                    },
            ),
            Row(children: [
              Expanded(child: OutlinedButton(onPressed: () => _pickTime(true), child: Text('Start ${_start.format(context)}'))),
              const SizedBox(width: 8),
              Expanded(child: OutlinedButton(onPressed: () => _pickTime(false), child: Text('End ${_end.format(context)}'))),
            ]),
            const SizedBox(height: 12),
            Row(children: [
              const Text('Break'),
              Expanded(
                child: Slider(
                  value: _break.toDouble(),
                  max: 120,
                  divisions: 24,
                  label: '$_break min',
                  onChanged: (v) => setState(() => _break = v.round()),
                ),
              ),
              Text('$_break min'),
            ]),
            SegmentedButton<String>(
              segments: const [
                ButtonSegment(value: 'office', label: Text('Office'), icon: Icon(Icons.business)),
                ButtonSegment(value: 'remote', label: Text('Remote'), icon: Icon(Icons.home_work_outlined)),
              ],
              selected: {_location},
              onSelectionChanged: (s) => setState(() => _location = s.first),
            ),
          ],
          const SizedBox(height: 12),
          TextField(controller: _reason, maxLength: 500, decoration: const InputDecoration(labelText: 'Reason')),
          if (_error != null) Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error)),
          const SizedBox(height: 8),
          FilledButton(onPressed: _send, child: const Text('Send request')),
        ]),
      ),
    );
  }
}
