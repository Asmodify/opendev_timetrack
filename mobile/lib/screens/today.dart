import 'dart:async';
import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../api.dart';
import '../main.dart' show officeColor, remoteColor;
import '../models.dart';
import 'sheets.dart';

/// The day view: a clock card on top and a timeline of the day's sessions.
/// Automatic sessions show as drafts until the worker reviews and confirms the day.
class TodayPage extends StatefulWidget {
  const TodayPage({super.key, required this.me, required this.projects, required this.onChanged});
  final Me me;
  final List<Project> projects;
  final Future<void> Function() onChanged;

  @override
  State<TodayPage> createState() => _TodayPageState();
}

class _TodayPageState extends State<TodayPage> {
  DateTime _day = DateUtils.dateOnly(DateTime.now());
  List<Entry>? _entries;
  String? _error;
  Timer? _ticker;
  int? _clockProject;

  bool get _isToday => DateUtils.isSameDay(_day, DateTime.now());

  @override
  void initState() {
    super.initState();
    _load();
    if (widget.me.running != null) {
      _ticker = Timer.periodic(const Duration(seconds: 1), (_) => setState(() {}));
    }
  }

  @override
  void dispose() {
    _ticker?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final rows = await Api.instance.entries(_day, _day);
      if (mounted) setState(() => _entries = rows..sort((a, b) => a.start.compareTo(b.start)));
    } on ApiError catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  void _toast(String text) => ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));

  Future<void> _clock() async {
    try {
      if (widget.me.running != null) {
        await Api.instance.clockOut();
        _toast('Clocked out');
      } else {
        await Api.instance.clockIn(projectId: _clockProject);
        _toast('Clocked in');
      }
      await widget.onChanged();
    } on ApiError catch (e) {
      _toast(e.message);
    }
  }

  Future<void> _confirmDay() async {
    try {
      final n = await Api.instance.confirmDay(_day);
      _toast(n == 1 ? '1 session confirmed' : '$n sessions confirmed');
      await _load();
    } on ApiError catch (e) {
      _toast(e.message);
    }
  }

  Future<void> _openEntry(Entry e) async {
    final changed = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => EntrySheet(entry: e, projects: widget.projects),
    );
    if (changed == true) await _load();
  }

  Future<void> _addHours() async {
    final sent = await showModalBottomSheet<bool>(
      context: context,
      isScrollControlled: true,
      showDragHandle: true,
      builder: (_) => CorrectionSheet(day: _day),
    );
    if (sent == true) _toast('Request sent to your manager');
  }

  void _shiftDay(int days) {
    final next = _day.add(Duration(days: days));
    if (next.isAfter(DateTime.now())) return;
    setState(() {
      _day = next;
      _entries = null;
    });
    _load();
  }

  @override
  Widget build(BuildContext context) {
    final entries = _entries;
    final drafts = entries?.where((e) => e.isDraft).length ?? 0;
    final total = entries?.fold<int>(0, (t, e) => t + e.workedSeconds) ?? 0;
    return RefreshIndicator(
      onRefresh: () async {
        await widget.onChanged();
      },
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 8, 16, 96),
        children: [
          if (_isToday) _ClockCard(me: widget.me, projects: widget.projects, project: _clockProject,
              onProject: (p) => setState(() => _clockProject = p), onPressed: _clock),
          const SizedBox(height: 12),
          Row(children: [
            IconButton(onPressed: () => _shiftDay(-1), icon: const Icon(Icons.chevron_left), tooltip: 'Previous day'),
            Expanded(
              child: Column(children: [
                Text(_isToday ? 'Today' : DateFormat.EEEE().format(_day), style: Theme.of(context).textTheme.titleMedium),
                Text(DateFormat.yMMMd().format(_day), style: Theme.of(context).textTheme.bodySmall),
              ]),
            ),
            IconButton(onPressed: _isToday ? null : () => _shiftDay(1), icon: const Icon(Icons.chevron_right), tooltip: 'Next day'),
          ]),
          Center(child: Text('${hm(total)} worked', style: Theme.of(context).textTheme.headlineSmall)),
          const SizedBox(height: 8),
          if (drafts > 0)
            Card(
              color: Theme.of(context).colorScheme.secondaryContainer,
              child: ListTile(
                leading: const Icon(Icons.auto_awesome),
                title: Text(drafts == 1 ? '1 automatic session to review' : '$drafts automatic sessions to review'),
                subtitle: const Text('Tap a session to add a project, then confirm your day.'),
                trailing: FilledButton(onPressed: _confirmDay, child: const Text('Confirm')),
              ),
            ),
          const SizedBox(height: 8),
          if (_error != null)
            Text(_error!, style: TextStyle(color: Theme.of(context).colorScheme.error))
          else if (entries == null)
            const Padding(padding: EdgeInsets.all(32), child: Center(child: CircularProgressIndicator()))
          else if (entries.isEmpty)
            Padding(
              padding: const EdgeInsets.all(32),
              child: Text(
                _isToday
                    ? 'No hours yet today. Clock in, or turn on office check-in in Settings so your day starts when you arrive.'
                    : 'No hours on this day. Use "Add hours" if you forgot to record them.',
                textAlign: TextAlign.center,
              ),
            )
          else
            _Timeline(entries: entries, onTap: _openEntry),
          const SizedBox(height: 12),
          OutlinedButton.icon(onPressed: _addHours, icon: const Icon(Icons.add), label: const Text('Add hours you forgot')),
        ],
      ),
    );
  }
}

class _ClockCard extends StatelessWidget {
  const _ClockCard({required this.me, required this.projects, required this.project, required this.onProject, required this.onPressed});
  final Me me;
  final List<Project> projects;
  final int? project;
  final ValueChanged<int?> onProject;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    final run = me.running;
    final cs = Theme.of(context).colorScheme;
    final working = run != null;
    final where = working ? run.location : me.here;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            Icon(Icons.circle, size: 10, color: working ? Colors.deepOrange : cs.outline),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                working ? 'Working · ${run.sourceLabel}' : 'Not working',
                style: Theme.of(context).textTheme.titleSmall,
              ),
            ),
            Chip(
              label: Text(where == 'office' ? 'Office' : 'Remote'),
              side: BorderSide(color: where == 'office' ? officeColor : remoteColor),
              visualDensity: VisualDensity.compact,
            ),
          ]),
          const SizedBox(height: 8),
          Text(
            working ? clockText(DateTime.now().difference(run.start)) : '0:00:00',
            style: Theme.of(context).textTheme.displaySmall?.copyWith(fontFeatures: const [FontFeature.tabularFigures()]),
          ),
          if (working) Text('Since ${DateFormat.Hm().format(run.start)}${run.project != null ? ' · ${run.project!.name}' : ''}'),
          if (!working && projects.isNotEmpty) ...[
            const SizedBox(height: 8),
            DropdownButtonFormField<int?>(
              initialValue: project,
              decoration: const InputDecoration(labelText: 'Project (optional)', isDense: true),
              items: [
                const DropdownMenuItem<int?>(value: null, child: Text('No project')),
                for (final p in projects) DropdownMenuItem<int?>(value: p.id, child: Text(p.name)),
              ],
              onChanged: onProject,
            ),
          ],
          const SizedBox(height: 12),
          FilledButton(
            style: working ? FilledButton.styleFrom(backgroundColor: Colors.deepOrange.shade700) : null,
            onPressed: onPressed,
            child: Padding(
              padding: const EdgeInsets.symmetric(vertical: 12),
              child: Text(working ? 'Clock out' : 'Clock in', style: const TextStyle(fontSize: 17)),
            ),
          ),
        ]),
      ),
    );
  }
}

/// A vertical timeline of the day, one block per session, in the style of a calendar day view.
class _Timeline extends StatelessWidget {
  const _Timeline({required this.entries, required this.onTap});
  final List<Entry> entries;
  final ValueChanged<Entry> onTap;

  static const _hourHeight = 56.0;
  static const _gutter = 44.0;

  @override
  Widget build(BuildContext context) {
    final day = DateUtils.dateOnly(entries.first.start);
    double hourOf(DateTime t) => t.difference(day).inMinutes / 60;
    var first = 7, last = 19;
    for (final e in entries) {
      first = math.min(first, hourOf(e.start).floor().clamp(0, 23));
      last = math.max(last, hourOf(e.end ?? DateTime.now()).ceil().clamp(1, 24));
    }
    final cs = Theme.of(context).colorScheme;
    final height = (last - first) * _hourHeight;

    return SizedBox(
      height: height + 8,
      child: LayoutBuilder(builder: (context, box) {
        return Stack(children: [
          for (var h = first; h <= last; h++)
            Positioned(
              top: (h - first) * _hourHeight,
              left: 0,
              right: 0,
              child: Row(children: [
                SizedBox(
                  width: _gutter,
                  child: Text('${h.toString().padLeft(2, '0')}:00', style: Theme.of(context).textTheme.labelSmall),
                ),
                Expanded(child: Divider(height: 1, color: cs.outlineVariant)),
              ]),
            ),
          for (final e in entries)
            _block(context, e, top: (hourOf(e.start) - first) * _hourHeight + 6,
                height: ((hourOf(e.end ?? DateTime.now()) - hourOf(e.start)) * _hourHeight).clamp(22.0, 2000.0),
                width: box.maxWidth - _gutter - 4),
        ]);
      }),
    );
  }

  Widget _block(BuildContext context, Entry e, {required double top, required double height, required double width}) {
    final color = e.project?.color ?? (e.location == 'office' ? officeColor : remoteColor);
    final end = e.end;
    final label = '${DateFormat.Hm().format(e.start)}–${end == null ? 'now' : DateFormat.Hm().format(end)}';
    return Positioned(
      top: top,
      left: _gutter,
      width: width,
      height: height,
      child: Material(
        color: color.withValues(alpha: e.isDraft ? 0.12 : 0.85),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(8),
          side: BorderSide(color: color, width: e.isDraft ? 1.5 : 0),
        ),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: () => onTap(e),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
            child: DefaultTextStyle(
              style: TextStyle(color: e.isDraft ? Theme.of(context).colorScheme.onSurface : Colors.white, fontSize: 12),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(
                  [e.project?.name ?? (e.location == 'office' ? 'Office' : 'Remote'), if (e.isDraft) 'Draft'].join(' · '),
                  style: const TextStyle(fontWeight: FontWeight.w700),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
                if (height > 36)
                  Text('$label · ${hm(e.workedSeconds)} · ${e.sourceLabel}', maxLines: 1, overflow: TextOverflow.ellipsis),
                if (height > 56 && e.note.isNotEmpty) Text(e.note, maxLines: 2, overflow: TextOverflow.ellipsis),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}
