import 'package:flutter/material.dart';
import 'package:intl/intl.dart';

import '../api.dart';
import '../main.dart' show officeColor, remoteColor;
import '../models.dart';

class WeekPage extends StatefulWidget {
  const WeekPage({super.key, required this.me});
  final Me me;

  @override
  State<WeekPage> createState() => _WeekPageState();
}

class _WeekPageState extends State<WeekPage> {
  Summary? _summary;
  String? _error;

  @override
  void initState() {
    super.initState();
    Api.instance.summary().then((s) {
      if (mounted) setState(() => _summary = s);
    }, onError: (Object e) {
      if (mounted) setState(() => _error = e.toString());
    });
  }

  @override
  Widget build(BuildContext context) {
    final s = _summary;
    if (_error != null) return Center(child: Text(_error!));
    if (s == null) return const Center(child: CircularProgressIndicator());
    final t = Theme.of(context).textTheme;
    final target = s.weeklyTargetHours * 3600;
    final daily = target / 5;
    final maxSeconds = [daily, ...s.days.map((d) => d.total.toDouble())].reduce((a, b) => a > b ? a : b) * 1.1;
    final office = s.days.fold<int>(0, (a, d) => a + d.office);
    final remote = s.days.fold<int>(0, (a, d) => a + d.remote);
    final today = DateUtils.dateOnly(DateTime.now());

    return ListView(padding: const EdgeInsets.all(16), children: [
      Row(children: [
        Expanded(child: _Stat(label: 'Today', value: hm(s.today))),
        Expanded(child: _Stat(label: 'This week', value: hm(s.week), sub: 'of ${s.weeklyTargetHours.toStringAsFixed(0)} h')),
        Expanded(child: _Stat(label: 'This month', value: hm(s.month))),
      ]),
      const SizedBox(height: 12),
      LinearProgressIndicator(value: target == 0 ? 0 : (s.week / target).clamp(0, 1), minHeight: 6),
      const SizedBox(height: 24),
      SizedBox(
        height: 180,
        child: Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
          for (final d in s.days)
            Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 4),
                child: Column(mainAxisAlignment: MainAxisAlignment.end, children: [
                  Text(d.total == 0 ? '–' : hm(d.total), style: t.labelSmall),
                  const SizedBox(height: 4),
                  Container(height: 130 * d.remote / maxSeconds, color: remoteColor),
                  Container(height: 130 * d.office / maxSeconds, color: officeColor),
                  const SizedBox(height: 4),
                  Text(DateFormat.E().format(d.date),
                      style: t.labelMedium?.copyWith(
                          fontWeight: DateUtils.isSameDay(d.date, today) ? FontWeight.w800 : FontWeight.w400)),
                ]),
              ),
            ),
        ]),
      ),
      const SizedBox(height: 12),
      Row(mainAxisAlignment: MainAxisAlignment.center, children: [
        const Icon(Icons.square, size: 12, color: officeColor),
        Text(' Office ${hm(office)}    '),
        const Icon(Icons.square, size: 12, color: remoteColor),
        Text(' Remote ${hm(remote)}'),
      ]),
    ]);
  }
}

class _Stat extends StatelessWidget {
  const _Stat({required this.label, required this.value, this.sub});
  final String label, value;
  final String? sub;

  @override
  Widget build(BuildContext context) {
    final t = Theme.of(context).textTheme;
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(label.toUpperCase(), style: t.labelSmall),
      Text(value, style: t.headlineSmall),
      if (sub != null) Text(sub!, style: t.bodySmall),
    ]);
  }
}
